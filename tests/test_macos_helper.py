"""The macOS password-free helper: a root launch daemon starts the app.

Covers the request validation, the path-safety check, the plist and the
install/uninstall command construction, the rate limit, the client fallback,
and a real unix-socket round trip (client <-> helper in-process, with a fake
launcher) that proves the framing and the size/timeout bounds.
"""
from __future__ import annotations

import json
import os
import shlex
import socket
import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from xrayui import elevate
from xrayui.core import macos_helper as h

# -- request validation ------------------------------------------------------

def test_a_clean_session_arg_is_accepted():
    assert h._validate_session_args(["--session-env=LANG=en_US.UTF-8"]) == \
        ["--session-env=LANG=en_US.UTF-8"]


def test_an_empty_session_is_fine():
    assert h._validate_session_args([]) == []


@pytest.mark.parametrize("arg", [
    "--session-env=LD_PRELOAD=/x",   # not on the whitelist
    "--session-env=QT_SCALE_FACTOR=1",  # on the whitelist, shown below
])
def test_unknown_keys_are_rejected(arg):
    if arg == "--session-env=QT_SCALE_FACTOR=1":
        # A whitelisted key passes; the unknown-key cases are the others.
        assert h._validate_session_args([arg]) == [arg]
        return
    with pytest.raises(h.Refusal):
        h._validate_session_args([arg])


def test_a_shell_metacharacter_is_rejected():
    with pytest.raises(h.Refusal):
        h._validate_session_args(["--session-env=LANG=a;b"])
    with pytest.raises(h.Refusal):
        h._validate_session_args(["--session-env=DISPLAY=:0`id`"])


def test_the_uid_is_never_taken_from_the_request():
    # The helper derives the uid from the peer, so SUDO_UID is refused.
    with pytest.raises(h.Refusal):
        h._validate_session_args(["--session-env=SUDO_UID=501"])


def test_an_oversize_value_is_rejected():
    with pytest.raises(h.Refusal):
        h._validate_session_args(["--session-env=LANG=" + "a" * (h._MAX_VALUE_LEN + 1)])


def test_a_non_string_session_item_is_rejected():
    with pytest.raises(h.Refusal):
        h._validate_session_args([123])


def test_a_non_list_session_is_rejected():
    with pytest.raises(h.Refusal):
        h._validate_session_args("LANG=en")


def test_a_duplicate_key_is_rejected():
    with pytest.raises(h.Refusal):
        h._validate_session_args(["--session-env=LANG=a", "--session-env=LANG=b"])


def test_a_request_with_an_unknown_key_is_rejected():
    with pytest.raises(h.Refusal):
        h._validate_request({"op": "launch", "session": [], "x": 1})


def test_a_request_with_a_bad_op_is_rejected():
    with pytest.raises(h.Refusal):
        h._validate_request({"op": "rm", "session": []})


def test_a_request_that_is_not_an_object_is_rejected():
    with pytest.raises(h.Refusal):
        h._validate_request([1, 2, 3])


def test_a_valid_request_returns_its_session():
    assert h._validate_request({"op": "launch",
                                "session": ["--session-env=LANG=en"]}) == \
        ["--session-env=LANG=en"]


# -- path safety -------------------------------------------------------------

def _fake_lstat(monkeypatch, entries: dict[str, tuple[int, int]],
                default: tuple[int, int] | None) -> None:
    """Make os.lstat return (uid, mode) for the given (resolved) paths.

    The real filesystem cannot be chowned without root, so ownership and mode
    are fabricated here; _path_is_safe only reads lstat. A path not in
    `entries` uses `default` when given, else raises FileNotFoundError. Keys
    are the resolved strings the module looks up, so the fake must not call
    resolve() itself (that would recurse back into lstat).
    """
    def fake_lstat(path, **kw):
        key = str(Path(path))
        if key in entries:
            uid, mode = entries[key]
        elif default is not None:
            uid, mode = default
        else:
            raise FileNotFoundError(path)
        st = types.SimpleNamespace(st_uid=uid, st_mode=mode)
        return st
    monkeypatch.setattr(os, "lstat", fake_lstat)


def _tree(monkeypatch, app: Path, app_uid: int, app_mode: int,
          parents: list[tuple[int, int]], *, missing: bool = False) -> None:
    """Create `app` on disk and fabricate its ownership up the chain to root.

    `parents` lists (uid, mode) for app.parent, app.parent.parent, ... in
    order; any level not listed is treated as root-owned 0o755 (the safe
    default), so the walk to the filesystem root succeeds. The files are
    created for real so `is_file()` is true; only the ownership/mode are
    fabricated, since chown needs root.
    """
    if not missing:
        app.parent.mkdir(parents=True, exist_ok=True)
        app.write_text("x")
    # Resolve the whole chain with the real lstat before patching it.
    chain = [app]
    p = app.parent
    while p != p.parent:
        chain.append(p)
        p = p.parent
    resolved = [str(x.resolve()) for x in chain]
    entries = {}
    if not missing:
        entries[resolved[0]] = (app_uid, app_mode)
    for key, (uid, mode) in zip(resolved[1:], parents, strict=False):
        entries[key] = (uid, mode)
    _fake_lstat(monkeypatch, entries, default=(0, 0o755))


def test_a_root_owned_app_in_a_root_owned_tree_is_safe(tmp_path, monkeypatch):
    app = tmp_path / "app" / "sushtun"
    _tree(monkeypatch, app, app_uid=0, app_mode=0o755,
          parents=[(0, 0o755), (0, 0o755)])
    assert h._path_is_safe(app, console_uid=501) is True


def test_a_user_owned_app_is_safe_for_that_user(tmp_path, monkeypatch):
    # A drag-installed .app is owned by the user who installed it.
    app = tmp_path / "app" / "sushtun"
    _tree(monkeypatch, app, app_uid=501, app_mode=0o755,
          parents=[(0, 0o755), (0, 0o755)])
    assert h._path_is_safe(app, console_uid=501) is True


def test_an_app_owned_by_someone_else_is_refused(tmp_path, monkeypatch):
    app = tmp_path / "app" / "sushtun"
    _tree(monkeypatch, app, app_uid=502, app_mode=0o755,
          parents=[(0, 0o755), (0, 0o755)])
    # Owned by uid 502: neither root nor the console user (501).
    assert h._path_is_safe(app, console_uid=501) is False


def test_a_world_writable_parent_is_refused(tmp_path, monkeypatch):
    app = tmp_path / "app" / "sushtun"
    _tree(monkeypatch, app, app_uid=0, app_mode=0o755,
          parents=[(0, 0o755), (0, 0o777)])  # a /tmp-like world-writable parent
    assert h._path_is_safe(app, console_uid=501) is False


def test_a_user_owned_parent_is_refused(tmp_path, monkeypatch):
    # A dev checkout: the parent is owned by the user, not root.
    app = tmp_path / "app" / "sushtun"
    _tree(monkeypatch, app, app_uid=0, app_mode=0o755,
          parents=[(0, 0o755), (501, 0o755)])
    assert h._path_is_safe(app, console_uid=501) is False


def test_a_missing_app_is_refused(tmp_path, monkeypatch):
    app = tmp_path / "nope" / "sushtun"
    _tree(monkeypatch, app, app_uid=0, app_mode=0o755, parents=[], missing=True)
    assert h._path_is_safe(app, console_uid=501) is False


def test_a_world_writable_app_is_refused(tmp_path, monkeypatch):
    app = tmp_path / "app" / "sushtun"
    _tree(monkeypatch, app, app_uid=0, app_mode=0o777,
          parents=[(0, 0o755), (0, 0o755)])
    assert h._path_is_safe(app, console_uid=501) is False


# -- plist -------------------------------------------------------------------

def test_the_plist_has_the_exact_keys():
    xml = h.plist_xml()
    assert f"<string>{h.LABEL}</string>" in xml
    assert "<string>--helper</string>" in xml
    assert "SockPathName" in xml
    assert f"<string>{h.SOCK_PATH}</string>" in xml
    assert f"<integer>{0o660}</integer>" in xml  # SockPathMode, decimal
    assert f"<integer>{h.HELPER_VERSION}</integer>" in xml  # Version


def test_the_plist_program_arguments_are_the_installed_app():
    xml = h.plist_xml(app_exe="/Applications/sushTun.app/Contents/MacOS/sushtun")
    assert "<string>/Applications/sushTun.app/Contents/MacOS/sushtun</string>" in xml
    # The app path comes before the --helper flag.
    assert xml.index("Contents/MacOS/sushtun") < xml.index("--helper")


def test_the_plist_escapes_xml_special_characters():
    assert h._plist_escape("a&b<c>d") == "a&amp;b&lt;c&gt;d"
    xml = h.plist_xml(app_exe="/Applications/a&b.app/x")
    assert "<string>/Applications/a&amp;b.app/x</string>" in xml


# -- install / uninstall command construction --------------------------------

def test_install_is_one_osascript_admin_prompt():
    cmds = h.install_commands(app_exe="/Applications/sushTun.app/Contents/MacOS/sushtun")
    assert len(cmds) == 1
    argv = cmds[0]
    assert argv[0] == "osascript" and argv[1] == "-e"
    script = argv[2]
    assert script.startswith("do shell script ")
    assert script.endswith(" with administrator privileges")


def test_install_writes_and_bootstraps_the_plist():
    inner = _inner_shell(h.install_commands()[0])
    assert "cat > " + str(h.PLIST_PATH) in inner
    assert "chown root:wheel " + str(h.PLIST_PATH) in inner
    assert "chmod 0644 " + str(h.PLIST_PATH) in inner
    assert "launchctl bootstrap system " + str(h.PLIST_PATH) in inner


def test_install_does_not_inject_through_a_path_with_spaces_or_quotes():
    # A path with spaces and a single quote must survive as one argv element.
    evil = "/Applications/O'Brien's App/Contents/MacOS/sushtun"
    inner = _inner_shell(h.install_commands(app_exe=evil)[0])
    # The app path appears verbatim (once) inside the plist, not split.
    assert evil in inner
    # And the heredoc is single-quoted, so nothing in the body is expanded.
    assert "<<'SUSHTUN_PLIST_EOF'" in inner


def _inner_shell(argv: list[str]) -> str:
    script = argv[2]
    body = script[len("do shell script "):-len(" with administrator privileges")]
    return shlex.split(body)[0]


def test_uninstall_bootouts_and_removes_plist_and_socket():
    inner = _inner_shell(h.uninstall_commands()[0])
    assert "launchctl bootout system " + h.LABEL in inner
    assert "rm -f " in inner
    assert str(h.PLIST_PATH) in inner
    assert str(h.SOCK_PATH) in inner


# -- rate limit --------------------------------------------------------------

def test_the_rate_limit_binds_the_count_per_window():
    rl = h.RateLimiter(limit=3, window=60)
    assert [rl.allow(t) for t in (0, 1, 2)] == [True, True, True]
    assert rl.allow(3) is False  # the fourth within the window
    assert rl.allow(61) is True  # the window has slid past the first hit


# -- the launch command ------------------------------------------------------

def test_the_launch_command_wraps_the_app_in_the_users_session(monkeypatch):
    monkeypatch.setattr(h, "_LAUNCHCTL", "/bin/launchctl")
    monkeypatch.setattr(os.path, "exists", lambda p: p == "/bin/launchctl")
    cmd = h._launch_command(501, ["--session-env=LANG=en"])
    assert cmd == ["/bin/launchctl", "asuser", "501", str(h.APP_EXE),
                   "--session-env=LANG=en"]


def test_the_launch_command_has_no_wrapper_for_root(monkeypatch):
    monkeypatch.setattr(h, "_LAUNCHCTL", "/bin/launchctl")
    cmd = h._launch_command(0, [])
    assert cmd == [str(h.APP_EXE)]


def test_the_launch_command_has_no_wrapper_without_launchctl(monkeypatch):
    monkeypatch.setattr(h, "_LAUNCHCTL", "/bin/launchctl")
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    assert h._launch_command(501, []) == [str(h.APP_EXE)]


# -- real unix socket: client <-> helper in-process --------------------------

_UNSET = object()


def _roundtrip(request: bytes, monkeypatch, *, peer_uid=_UNSET, console_uid=_UNSET,
               already_running=False, safe=True, rate=None) -> dict:
    """Run one request through the real _serve_one over a real socketpair.

    The client writes `request` and reads the whole reply; the helper side is
    the real _serve_one with the launcher, peer, path and rate mocked.
    """
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    if peer_uid is not _UNSET:
        monkeypatch.setattr(h, "_getpeereid", lambda fd: peer_uid)
    if console_uid is not _UNSET:
        monkeypatch.setattr(h, "_console_uid", lambda: console_uid)
    monkeypatch.setattr(h, "_path_is_safe", lambda p, u: safe)
    monkeypatch.setattr(h, "_already_running", lambda: already_running)
    if rate is not None:
        monkeypatch.setattr(h, "_RATE", rate)
    spawned = []
    monkeypatch.setattr(h, "_spawn", lambda cmd: spawned.append(cmd))

    def server():
        try:
            h._serve_one(a)
        finally:
            a.close()

    t = threading.Thread(target=server, daemon=True)
    t.start()
    # A peer-refused request makes the server refuse before reading, so it can
    # close before this sendall lands: the reply is still sent, so the broken
    # send is harmless.
    try:
        b.sendall(request)
    except (BrokenPipeError, ConnectionResetError):
        pass
    chunks = []
    while True:
        try:
            data = b.recv(4096)
        except (ConnectionResetError, OSError):
            break
        if not data:
            break
        chunks.append(data)
    b.close()
    t.join(timeout=5)
    return json.loads(b"".join(chunks).decode("utf-8"))


def test_a_ping_gets_a_pong_with_the_version(monkeypatch):
    reply = _roundtrip(json.dumps({"op": "ping"}).encode(), monkeypatch,
                       peer_uid=501, console_uid=501)
    assert reply["op"] == "pong"
    assert reply["version"] == h.__version__
    assert reply["helper"] == h.HELPER_VERSION


def test_a_valid_launch_starts_the_app_in_the_users_session(monkeypatch):
    reply = _roundtrip(
        json.dumps({"op": "launch", "session": ["--session-env=LANG=en"]}).encode(),
        monkeypatch, peer_uid=501, console_uid=501)
    assert reply["op"] == "started"


def test_a_root_peer_is_refused(monkeypatch):
    reply = _roundtrip(json.dumps({"op": "ping"}).encode(), monkeypatch,
                       peer_uid=0, console_uid=501)
    assert reply["op"] == "refused"
    assert "root" in reply["reason"]


def test_an_unknown_peer_is_refused(monkeypatch):
    reply = _roundtrip(json.dumps({"op": "ping"}).encode(), monkeypatch,
                       peer_uid=-1, console_uid=501)
    assert reply["op"] == "refused"


def test_a_peer_that_is_not_the_console_user_is_refused(monkeypatch):
    reply = _roundtrip(json.dumps({"op": "ping"}).encode(), monkeypatch,
                       peer_uid=502, console_uid=501)
    assert reply["op"] == "refused"
    assert "console" in reply["reason"]


def test_an_unresolvable_console_user_is_refused(monkeypatch):
    reply = _roundtrip(json.dumps({"op": "ping"}).encode(), monkeypatch,
                       peer_uid=501, console_uid=None)
    assert reply["op"] == "refused"


def test_bad_json_is_refused(monkeypatch):
    reply = _roundtrip(b"this is not json", monkeypatch,
                       peer_uid=501, console_uid=501)
    assert reply["op"] == "refused"


def test_an_oversize_request_is_refused(monkeypatch):
    big = b'{"op":"ping","pad":"' + b"a" * (h.MAX_REQUEST + 1) + b'"}'
    reply = _roundtrip(big, monkeypatch, peer_uid=501, console_uid=501)
    assert reply["op"] == "refused"
    assert "large" in reply["reason"]


def test_an_unknown_request_key_is_refused(monkeypatch):
    reply = _roundtrip(json.dumps({"op": "launch", "session": [], "x": 1}).encode(),
                       monkeypatch, peer_uid=501, console_uid=501)
    assert reply["op"] == "refused"


def test_an_unknown_session_key_is_refused(monkeypatch):
    reply = _roundtrip(
        json.dumps({"op": "launch", "session": ["--session-env=LD_PRELOAD=/x"]}).encode(),
        monkeypatch, peer_uid=501, console_uid=501)
    assert reply["op"] == "refused"


def test_an_unsafe_app_path_is_refused(monkeypatch):
    reply = _roundtrip(json.dumps({"op": "launch", "session": []}).encode(),
                       monkeypatch, peer_uid=501, console_uid=501, safe=False)
    assert reply["op"] == "refused"
    assert "installed app" in reply["reason"]


def test_a_second_launch_while_one_runs_is_already_running(monkeypatch):
    reply = _roundtrip(json.dumps({"op": "launch", "session": []}).encode(),
                       monkeypatch, peer_uid=501, console_uid=501,
                       already_running=True)
    assert reply["op"] == "already running"


def test_a_rate_limited_launch_is_refused(monkeypatch):
    exhausted = h.RateLimiter(limit=1, window=60)
    exhausted.allow()  # use the one slot, on the same clock _serve_one uses
    reply = _roundtrip(json.dumps({"op": "launch", "session": []}).encode(),
                       monkeypatch, peer_uid=501, console_uid=501, rate=exhausted)
    assert reply["op"] == "refused"
    assert "rate" in reply["reason"]


def test_a_ping_is_not_rate_limited(monkeypatch):
    exhausted = h.RateLimiter(limit=1, window=60)
    exhausted.allow()
    reply = _roundtrip(json.dumps({"op": "ping"}).encode(), monkeypatch,
                       peer_uid=501, console_uid=501, rate=exhausted)
    assert reply["op"] == "pong"


def test_should_offer_is_false_for_a_source_run(monkeypatch):
    monkeypatch.setattr(h, "_is_mac", lambda: True)
    from xrayui import paths
    monkeypatch.setattr(paths, "installed", lambda: False)
    assert h.should_offer() is False


def test_should_offer_is_false_when_the_helper_is_already_healthy(monkeypatch):
    monkeypatch.setattr(h, "_is_mac", lambda: True)
    from xrayui import paths
    monkeypatch.setattr(paths, "installed", lambda: True)
    monkeypatch.setattr(h, "healthy", lambda: True)
    assert h.should_offer() is False


def test_should_offer_is_true_when_the_helper_is_stale_or_absent(monkeypatch):
    monkeypatch.setattr(h, "_is_mac", lambda: True)
    from xrayui import paths
    monkeypatch.setattr(paths, "installed", lambda: True)
    monkeypatch.setattr(h, "healthy", lambda: False)
    assert h.should_offer() is True


def test_should_offer_is_false_off_macos(monkeypatch):
    monkeypatch.setattr(h, "_is_mac", lambda: False)
    from xrayui import paths
    monkeypatch.setattr(paths, "installed", lambda: True)
    assert h.should_offer() is False


# -- the client side over a real listening socket ----------------------------

_sock_counter = 0


def _next_sock() -> Path:
    # AF_UNIX paths are short on macOS (~104 bytes); a pytest tmp_path is too
    # long, so bind in /tmp with a unique, short name.
    global _sock_counter
    _sock_counter += 1
    return Path("/tmp") / f"sushtun-h-{os.getpid()}-{_sock_counter}.sock"


def _serve_thread(sock_path: Path, monkeypatch, replies) -> threading.Thread:
    """A real unix server that answers with canned replies."""
    sock_path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(4)

    def run():
        while replies:
            conn, _ = server.accept()
            try:
                conn.recv(4096)
                conn.sendall(json.dumps(replies.pop(0)).encode("utf-8"))
            finally:
                conn.close()
        server.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def test_the_client_launch_sends_the_request_and_reads_started(monkeypatch):
    sock = _next_sock()
    t = _serve_thread(sock, monkeypatch, [{"op": "started"}])
    monkeypatch.setattr(h, "SOCK_PATH", sock)
    assert h.launch(["--session-env=LANG=en"]) == "started"
    t.join(timeout=5)


def test_the_client_launch_reads_already_running(monkeypatch):
    sock = _next_sock()
    t = _serve_thread(sock, monkeypatch, [{"op": "already running"}])
    monkeypatch.setattr(h, "SOCK_PATH", sock)
    assert h.launch([]) == "already running"
    t.join(timeout=5)


def test_the_client_launch_raises_on_a_refusal(monkeypatch):
    sock = _next_sock()
    t = _serve_thread(sock, monkeypatch, [{"op": "refused", "reason": "nope"}])
    monkeypatch.setattr(h, "SOCK_PATH", sock)
    with pytest.raises(h.Refusal):
        h.launch([])
    t.join(timeout=5)


def test_the_client_ping_reads_the_version(monkeypatch):
    sock = _next_sock()
    t = _serve_thread(sock, monkeypatch,
                      [{"op": "pong", "version": h.__version__,
                        "helper": h.HELPER_VERSION}])
    monkeypatch.setattr(h, "SOCK_PATH", sock)
    assert h.ping() == {"op": "pong", "version": h.__version__,
                        "helper": h.HELPER_VERSION}
    t.join(timeout=5)


def test_the_client_ping_is_none_when_absent(monkeypatch):
    monkeypatch.setattr(h, "SOCK_PATH", Path("/tmp") / "sushtun-absent.sock")
    assert h.ping() is None


def test_the_client_launch_is_a_refusal_when_absent(monkeypatch):
    monkeypatch.setattr(h, "SOCK_PATH", Path("/tmp") / "sushtun-absent.sock")
    with pytest.raises(h.Refusal):
        h.launch([])


def test_healthy_is_true_only_for_the_matching_version(monkeypatch):
    sock = _next_sock()
    t = _serve_thread(sock, monkeypatch,
                      [{"op": "pong", "version": h.__version__,
                        "helper": h.HELPER_VERSION}])
    monkeypatch.setattr(h, "SOCK_PATH", sock)
    assert h.healthy() is True
    t.join(timeout=5)


def test_a_stale_version_helper_is_not_healthy(monkeypatch):
    # A version mismatch means the plist is stale: reinstall, not silent use.
    sock = _next_sock()
    t = _serve_thread(sock, monkeypatch,
                      [{"op": "pong", "version": "0.0.1",
                        "helper": h.HELPER_VERSION}])
    monkeypatch.setattr(h, "SOCK_PATH", sock)
    assert h.healthy() is False
    t.join(timeout=5)


def test_status_reports_installed_and_healthy(tmp_path, monkeypatch):
    sock = _next_sock()
    plist = tmp_path / "helper.plist"
    plist.write_text("x")
    t = _serve_thread(sock, monkeypatch,
                      [{"op": "pong", "version": h.__version__,
                        "helper": h.HELPER_VERSION}])
    monkeypatch.setattr(h, "SOCK_PATH", sock)
    monkeypatch.setattr(h, "PLIST_PATH", plist)
    st = h.status()
    assert st["installed"] is True
    assert st["healthy"] is True
    assert st["running_version"] == h.__version__
    t.join(timeout=5)


# -- the client fallback in elevate.py ---------------------------------------

def test_a_source_run_never_uses_the_helper(monkeypatch):
    # Not installed: the helper path is skipped, so the osascript prompt is
    # the only option. launch() must never be called.
    monkeypatch.setattr(elevate, "IS_MAC", True)
    from xrayui import paths
    monkeypatch.setattr(paths, "installed", lambda: False)

    def boom(session):
        raise AssertionError("the helper must not be used for a source run")
    monkeypatch.setattr(h, "launch", boom)
    assert elevate._relaunch_macos_via_helper() is False


def test_an_installed_app_uses_the_helper_when_it_starts(monkeypatch):
    monkeypatch.setattr(elevate, "IS_MAC", True)
    from xrayui import paths
    monkeypatch.setattr(paths, "installed", lambda: True)
    monkeypatch.setattr(h, "healthy", lambda: True)
    monkeypatch.setattr(elevate, "_session_args",
                        lambda: ["--session-env=LANG=en",
                                 "--session-env=SUDO_UID=501"])
    seen = {}
    monkeypatch.setattr(h, "launch",
                        lambda session: seen.setdefault("session", session) or "started")
    assert elevate._relaunch_macos_via_helper() is True
    # SUDO_UID is dropped: the helper derives the uid from the peer.
    assert seen["session"] == ["--session-env=LANG=en"]


def test_an_unhealthy_helper_falls_back_to_osascript(monkeypatch):
    # Installed but the helper is absent/stale: not used, so the password
    # prompt is the fallback and should_offer() can present (re)install.
    monkeypatch.setattr(elevate, "IS_MAC", True)
    from xrayui import paths
    monkeypatch.setattr(paths, "installed", lambda: True)
    monkeypatch.setattr(h, "healthy", lambda: False)

    def boom(session):
        raise AssertionError("an unhealthy helper must not be launched")
    monkeypatch.setattr(h, "launch", boom)
    assert elevate._relaunch_macos_via_helper() is False


def test_the_helper_falls_back_to_osascript_on_refusal(monkeypatch):
    monkeypatch.setattr(elevate, "IS_MAC", True)
    from xrayui import paths
    monkeypatch.setattr(paths, "installed", lambda: True)
    monkeypatch.setattr(h, "healthy", lambda: True)
    monkeypatch.setattr(elevate, "_session_args", lambda: [])

    def refuse(session):
        raise h.Refusal("nope")
    monkeypatch.setattr(h, "launch", refuse)
    assert elevate._relaunch_macos_via_helper() is False


def test_relaunch_macos_tries_the_helper_then_osascript(monkeypatch):
    # The helper refuses, so _relaunch_macos must fall through to osascript.
    monkeypatch.setattr(elevate, "IS_MAC", True)
    monkeypatch.setattr(elevate, "_relaunch_macos_via_helper", lambda: False)
    order = []
    monkeypatch.setattr(elevate, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(elevate, "_session_args", lambda: [])
    monkeypatch.setattr(elevate, "_session_launch_prefix", lambda: [])
    monkeypatch.setattr(elevate, "_elevated_cmd", lambda: ["/app/x"])
    monkeypatch.setattr(elevate.os, "getuid", lambda: 501)
    monkeypatch.setattr(elevate, "_LAUNCHCTL", "/nonexistent")

    def fake_run(args, **kw):
        order.append(args[0])
        return MagicMock(returncode=0, stdout="1\n", stderr="")
    monkeypatch.setattr(elevate.subprocess, "run", fake_run)
    assert elevate._relaunch_macos() is True
    assert order == ["osascript"]  # the password prompt was used


def test_relaunch_macos_skips_osascript_when_the_helper_starts(monkeypatch):
    monkeypatch.setattr(elevate, "IS_MAC", True)
    monkeypatch.setattr(elevate, "_relaunch_macos_via_helper", lambda: True)
    order = []

    def fake_run(args, **kw):
        order.append(args[0])
        return MagicMock(returncode=0, stdout="1\n", stderr="")
    monkeypatch.setattr(elevate.subprocess, "run", fake_run)
    assert elevate._relaunch_macos() is True
    assert order == []  # no password prompt


# -- the app_main.py flag routing --------------------------------------------

def test_the_helper_flag_runs_the_launcher_not_the_gui(monkeypatch):
    import app_main
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["sushtun", "--helper"])
    with monkeypatch.context() as m:
        m.setattr(h, "run_helper", lambda: 7)
        assert app_main._helper_flag() == 7


def test_the_uninstall_helper_flag_uninstalls_and_exits(monkeypatch):
    import app_main
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "argv", ["sushtun", "--uninstall-helper"])
    with monkeypatch.context() as m:
        m.setattr(h, "uninstall", lambda: True)
        assert app_main._helper_flag() == 0


def test_the_helper_flags_are_macos_only(monkeypatch):
    import app_main
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "argv", ["sushtun", "--helper"])
    assert app_main._helper_flag() is None  # other OSes are untouched
