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
import stat
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


# -- path safety: the whole bundle tree must be root-owned -------------------

def _make_bundle(tmp_path: Path) -> Path:
    """A real .app tree on disk: bundle/Contents/MacOS/sushtun + a dylib."""
    bundle = tmp_path / "sushTun.app"
    exe_dir = bundle / "Contents" / "MacOS"
    exe_dir.mkdir(parents=True)
    (exe_dir / "sushtun").write_text("x")
    (bundle / "Contents" / "Frameworks").mkdir()
    (bundle / "Contents" / "Frameworks" / "libfoo.dylib").write_text("x")
    return bundle


def _fake_bundle(monkeypatch, bundle: Path,
                 overrides: dict[str, tuple[int, int]] | None = None) -> None:
    """Fabricate ownership/mode for the bundle tree (chown needs root).

    The real files exist so os.walk and realpath work; only st_uid and the
    writable bits are fabricated. `overrides` maps a bundle-relative path to
    (uid, mode); everything else is root-owned 0o755. Parents above the bundle
    default to root-owned 0o755.
    """
    overrides = overrides or {}

    def real_type(p: Path) -> int:
        st = os.lstat(p)  # real, before the patch is applied
        if stat.S_ISLNK(st.st_mode):
            return stat.S_IFLNK
        if stat.S_ISDIR(st.st_mode):
            return stat.S_IFDIR
        return stat.S_IFREG

    entries = {str(bundle): (0, stat.S_IFDIR | 0o755)}
    for dirpath, dirnames, filenames in os.walk(bundle, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            entries[str(p)] = (0, real_type(p) | 0o755)
    for rel, (uid, mode) in overrides.items():
        p = bundle / rel
        entries[str(p)] = (uid, real_type(p) | mode)

    def fake_lstat(path, **kw):
        key = str(Path(path))
        uid, mode = entries.get(key, (0, stat.S_IFDIR | 0o755))
        return types.SimpleNamespace(st_uid=uid, st_mode=mode)
    monkeypatch.setattr(os, "lstat", fake_lstat)


def test_a_root_owned_hardened_bundle_is_safe(tmp_path, monkeypatch):
    bundle = _make_bundle(tmp_path)
    _fake_bundle(monkeypatch, bundle)
    assert h._bundle_is_safe(bundle) is True


def test_a_user_owned_bundle_is_refused(tmp_path, monkeypatch):
    bundle = _make_bundle(tmp_path)
    _fake_bundle(monkeypatch, bundle, {".": (501, 0o755)})
    assert h._bundle_is_safe(bundle) is False


def test_a_group_writable_bundle_dir_is_refused(tmp_path, monkeypatch):
    # An admin-group user could swap the bundle dir if it were group-writable.
    bundle = _make_bundle(tmp_path)
    _fake_bundle(monkeypatch, bundle, {".": (0, 0o775)})
    assert h._bundle_is_safe(bundle) is False


def test_a_user_writable_inner_file_is_refused(tmp_path, monkeypatch):
    # One user-writable dylib is enough: the root daemon would run it.
    bundle = _make_bundle(tmp_path)
    _fake_bundle(monkeypatch, bundle,
                 {"Contents/Frameworks/libfoo.dylib": (0, 0o777)})
    assert h._bundle_is_safe(bundle) is False


def test_a_user_owned_inner_file_is_refused(tmp_path, monkeypatch):
    bundle = _make_bundle(tmp_path)
    _fake_bundle(monkeypatch, bundle,
                 {"Contents/MacOS/sushtun": (501, 0o755)})
    assert h._bundle_is_safe(bundle) is False


def test_a_symlink_escaping_the_bundle_is_refused(tmp_path, monkeypatch):
    bundle = _make_bundle(tmp_path)
    outside = tmp_path / "evil.dylib"
    outside.write_text("x")
    link = bundle / "Contents" / "Frameworks" / "libevil.dylib"
    os.symlink(outside, link)
    _fake_bundle(monkeypatch, bundle)  # the link itself is root-owned
    assert h._bundle_is_safe(bundle) is False


def test_a_symlink_staying_inside_the_bundle_is_ok(tmp_path, monkeypatch):
    bundle = _make_bundle(tmp_path)
    target = bundle / "Contents" / "Frameworks" / "libfoo.dylib"
    link = bundle / "Contents" / "Frameworks" / "liblink.dylib"
    os.symlink(target, link)
    _fake_bundle(monkeypatch, bundle)
    assert h._bundle_is_safe(bundle) is True


def test_a_world_writable_parent_is_refused(tmp_path, monkeypatch):
    # A /tmp-like world-writable parent: the bundle could be swapped.
    bundle = _make_bundle(tmp_path)
    _fake_bundle(monkeypatch, bundle)
    # Force the bundle's parent to be world-writable.
    monkeypatch.setattr(h, "_parents_are_safe", lambda p: False)
    assert h._bundle_is_safe(bundle) is False


def test_a_missing_bundle_is_refused(tmp_path, monkeypatch):
    assert h._bundle_is_safe(tmp_path / "nope" / "sushTun.app") is False


# -- plist -------------------------------------------------------------------

def test_the_plist_has_the_exact_keys():
    xml = h.plist_xml()
    assert f"<string>{h.LABEL}</string>" in xml
    assert "<string>--helper</string>" in xml
    assert "SockPathName" in xml
    assert f"<string>{h.SOCK_PATH}</string>" in xml
    assert f"<integer>{0o660}</integer>" in xml  # SockPathMode, decimal
    assert f"<integer>{h.HELPER_VERSION}</integer>" in xml  # Version


def test_the_plist_program_arguments_are_the_hardened_copy():
    # The daemon runs the root-owned copy, not the /Applications original.
    xml = h.plist_xml()
    assert f"<string>{h.HELPER_APP_EXE}</string>" in xml
    assert "/Library/PrivilegedHelperTools/sushTun.app" in xml
    # The app path comes before the --helper flag.
    assert xml.index("Contents/MacOS/sushtun") < xml.index("--helper")


def test_the_plist_escapes_xml_special_characters():
    assert h._plist_escape("a&b<c>d") == "a&amp;b&lt;c&gt;d"
    xml = h.plist_xml(app_exe="/Library/a&b.app/x")
    assert "<string>/Library/a&amp;b.app/x</string>" in xml


# -- install / uninstall command construction --------------------------------

def test_install_is_one_osascript_admin_prompt():
    cmds = h.install_commands()
    assert len(cmds) == 1
    argv = cmds[0]
    assert argv[0] == "osascript" and argv[1] == "-e"
    script = argv[2]
    assert script.startswith("do shell script ")
    assert script.endswith(" with administrator privileges")


def test_install_copies_and_hardens_the_bundle():
    # The single admin prompt copies the app to a root:wheel location and
    # hardens it (chown -R root:wheel, chmod -R go-w) so no user can modify a
    # file the root daemon will execute.
    inner = _inner_shell(h.install_commands()[0])
    assert "cp -R " + str(h.SOURCE_APP) + " " + str(h.HELPER_APP_DIR) in inner
    assert "chown -R root:wheel " + str(h.HELPER_APP_DIR) in inner
    assert "chmod -R go-w " + str(h.HELPER_APP_DIR) in inner
    # The hardened copy's parent is made root:wheel 0755 (not group-writable).
    assert "chown root:wheel " + str(h.HELPER_APP_DIR.parent) in inner
    assert "chmod 0755 " + str(h.HELPER_APP_DIR.parent) in inner


def test_install_writes_and_bootstraps_the_plist():
    inner = _inner_shell(h.install_commands()[0])
    assert "cat > " + str(h.PLIST_PATH) in inner
    assert "chown root:wheel " + str(h.PLIST_PATH) in inner
    assert "chmod 0644 " + str(h.PLIST_PATH) in inner
    assert "launchctl bootstrap system " + str(h.PLIST_PATH) in inner


def test_install_recopies_on_reinstall():
    # A version change must replace the copy, not keep a stale one.
    inner = _inner_shell(h.install_commands()[0])
    assert "rm -rf " + str(h.HELPER_APP_DIR) in inner
    # bootout before bootstrap so a live job does not block the reinstall.
    assert "launchctl bootout system " + h.LABEL in inner


def test_install_does_not_inject_through_a_path_with_spaces_or_quotes():
    # A source path with spaces and a single quote must survive as one element.
    evil = "/Applications/O'Brien's App"
    inner = _inner_shell(h.install_commands(source_app=evil)[0])
    # The source path is shlex-quoted, so it is one token in the cp, not split
    # into several (which would let the quote inject a command).
    assert "cp -R " + shlex.quote(evil) in inner
    # And the heredoc is single-quoted, so nothing in the body is expanded.
    assert "<<'SUSHTUN_PLIST_EOF'" in inner


def _inner_shell(argv: list[str]) -> str:
    script = argv[2]
    body = script[len("do shell script "):-len(" with administrator privileges")]
    return shlex.split(body)[0]


def test_uninstall_bootouts_and_removes_copy_plist_and_socket():
    inner = _inner_shell(h.uninstall_commands()[0])
    assert "launchctl bootout system " + h.LABEL in inner
    assert "rm -rf " + str(h.HELPER_APP_DIR) in inner
    assert str(h.PLIST_PATH) in inner
    assert str(h.SOCK_PATH) in inner


def test_install_verifies_the_copy_and_reports_healthy(monkeypatch):
    monkeypatch.setattr(h, "_is_mac", lambda: True)
    monkeypatch.setattr(h, "subprocess", MagicMock(
        run=MagicMock(return_value=MagicMock(returncode=0))))
    monkeypatch.setattr(h, "_bundle_is_safe", lambda p: True)
    monkeypatch.setattr(h, "healthy", lambda: True)
    assert h.install() is True


def test_install_rolls_back_when_the_copy_is_not_safe(monkeypatch):
    # The elevated step ran, but the copy is not safe to run as root: the
    # install must undo it (uninstall) and report failure, keeping the
    # password prompt.
    monkeypatch.setattr(h, "_is_mac", lambda: True)
    runs = []
    monkeypatch.setattr(h, "subprocess", MagicMock(
        run=lambda argv, **k: runs.append(argv) or MagicMock(returncode=0)))
    monkeypatch.setattr(h, "_bundle_is_safe", lambda p: False)
    assert h.install() is False
    # The rollback ran the uninstall commands: a second osascript that removes
    # the plist (rm -f <plist>), which the install script (cat > <plist>) does
    # not do.
    assert len(runs) == 2
    assert "rm -f " + str(h.PLIST_PATH) in runs[1][2]


# -- rate limit --------------------------------------------------------------

def test_the_rate_limit_binds_the_count_per_window():
    rl = h.RateLimiter(limit=3, window=60)
    assert [rl.allow(t) for t in (0, 1, 2)] == [True, True, True]
    assert rl.allow(3) is False  # the fourth within the window
    assert rl.allow(61) is True  # the window has slid past the first hit


# -- the launch command ------------------------------------------------------

def test_the_launch_command_runs_the_hardened_copy_in_the_users_session(monkeypatch):
    monkeypatch.setattr(h, "_LAUNCHCTL", "/bin/launchctl")
    monkeypatch.setattr(os.path, "exists", lambda p: p == "/bin/launchctl")
    cmd = h._launch_command(501, ["--session-env=LANG=en"])
    assert cmd == ["/bin/launchctl", "asuser", "501", str(h.HELPER_APP_EXE),
                   "--session-env=LANG=en"]


def test_the_launch_command_has_no_wrapper_for_root(monkeypatch):
    monkeypatch.setattr(h, "_LAUNCHCTL", "/bin/launchctl")
    cmd = h._launch_command(0, [])
    assert cmd == [str(h.HELPER_APP_EXE)]


def test_the_launch_command_has_no_wrapper_without_launchctl(monkeypatch):
    monkeypatch.setattr(h, "_LAUNCHCTL", "/bin/launchctl")
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    assert h._launch_command(501, []) == [str(h.HELPER_APP_EXE)]


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
    monkeypatch.setattr(h, "_bundle_is_safe", lambda p: safe)
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


def test_an_unsafe_bundle_is_refused(monkeypatch):
    reply = _roundtrip(json.dumps({"op": "launch", "session": []}).encode(),
                       monkeypatch, peer_uid=501, console_uid=501, safe=False)
    assert reply["op"] == "refused"
    assert "root-owned" in reply["reason"]


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
