"""userfs: privilege-drop file writes via subprocess, and the symlink,
timeout and root-only-flags behavior that must hold.

filterwarnings("error::DeprecationWarning") turns a stray fork()
warning into a test failure outright -- this module must never call
os.fork() again, since that's exactly the multi-threaded-process
deadlock risk it was rewritten to avoid.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from xrayui.core import userfs

pytestmark = pytest.mark.filterwarnings("error::DeprecationWarning")


def test_write_as_user_refuses_a_symlinked_destination(tmp_path):
    real_target = tmp_path / "real_secret.txt"
    real_target.write_text("original", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real_target)

    with pytest.raises(userfs.UserFsError):
        userfs.write_as_user(link, b"attacker data", uid=os.getuid(), gid=os.getgid())

    assert real_target.read_text(encoding="utf-8") == "original"
    assert link.is_symlink()


def test_write_as_user_writes_a_normal_file(tmp_path):
    dest = tmp_path / "out.txt"
    userfs.write_as_user(dest, b"hello", uid=os.getuid(), gid=os.getgid())
    assert dest.read_bytes() == b"hello"
    assert oct(dest.stat().st_mode & 0o777) == "0o644"


def test_write_as_user_creates_missing_parent_directories(tmp_path):
    dest = tmp_path / "a" / "b" / "out.txt"
    userfs.write_as_user(dest, b"x", uid=os.getuid(), gid=os.getgid())
    assert dest.read_bytes() == b"x"


def test_write_as_user_overwrites_and_truncates_an_existing_longer_file(tmp_path):
    dest = tmp_path / "out.txt"
    dest.write_text("much longer than the replacement", encoding="utf-8")
    userfs.write_as_user(dest, b"new", uid=os.getuid(), gid=os.getgid())
    assert dest.read_bytes() == b"new"


def test_unlink_as_user_removes_the_file(tmp_path):
    dest = tmp_path / "gone.txt"
    dest.write_text("x", encoding="utf-8")
    userfs.unlink_as_user(dest, uid=os.getuid(), gid=os.getgid())
    assert not dest.exists()


def test_unlink_as_user_missing_ok_default_does_not_raise(tmp_path):
    userfs.unlink_as_user(tmp_path / "never-existed.txt", uid=os.getuid(), gid=os.getgid())


def test_unlink_as_user_missing_ok_false_raises(tmp_path):
    with pytest.raises(userfs.UserFsError):
        userfs.unlink_as_user(tmp_path / "never-existed.txt", uid=os.getuid(),
                              gid=os.getgid(), missing_ok=False)


def test_unlink_as_user_never_follows_a_symlink_to_remove_its_target(tmp_path):
    real_target = tmp_path / "real.txt"
    real_target.write_text("keep me", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real_target)

    userfs.unlink_as_user(link, uid=os.getuid(), gid=os.getgid())

    assert not link.exists()
    assert real_target.read_text(encoding="utf-8") == "keep me"


def test_run_as_user_raises_on_a_timeout(tmp_path):
    with pytest.raises(userfs.UserFsError, match="timed out"):
        userfs._run_as_user(["sleep", "5"], os.getuid(), os.getgid(), timeout=0.5)


def test_run_as_user_passes_user_group_only_when_root(monkeypatch):
    captured = []

    def fake_run(argv, **kwargs):
        captured.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(userfs.subprocess, "run", fake_run)
    monkeypatch.setattr(userfs.shutil, "which", lambda name, path=None: f"/usr/bin/{name}")

    monkeypatch.setattr(userfs.os, "geteuid", lambda: 0)
    userfs._run_as_user([userfs._tool("true")], 1234, 5678)
    argv, kwargs = captured[-1]
    assert kwargs["user"] == 1234
    assert kwargs["group"] == 5678
    assert kwargs["extra_groups"] == []

    monkeypatch.setattr(userfs.os, "geteuid", lambda: 1000)
    userfs._run_as_user([userfs._tool("true")], 1234, 5678)
    argv, kwargs = captured[-1]
    assert "user" not in kwargs
    assert "group" not in kwargs
    assert "extra_groups" not in kwargs


def test_write_as_user_resolves_tools_to_absolute_paths_not_inherited_path(monkeypatch):
    captured = []

    def fake_run(argv, **kwargs):
        captured.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(userfs.subprocess, "run", fake_run)
    monkeypatch.setattr(userfs.shutil, "which", lambda name, path=None: f"/usr/bin/{name}")

    userfs.write_as_user(Path("/tmp/x"), b"x", uid=os.getuid(), gid=os.getgid())

    for argv in captured:
        assert argv[0].startswith("/usr/bin/")


def test_run_as_user_reports_the_last_stderr_line_on_failure(monkeypatch):
    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"line one\nline two\n")

    monkeypatch.setattr(userfs.subprocess, "run", fake_run)
    with pytest.raises(userfs.UserFsError, match="line two"):
        userfs._run_as_user(["/bin/false"], os.getuid(), os.getgid())


def test_save_for_user_writes_where_o_nofollow_does_not_exist(monkeypatch, tmp_path):
    # Windows has neither O_NOFOLLOW nor an invoking-user id, so save_for_user
    # falls through to the plain write -- and naming os.O_NOFOLLOW there raises
    # an AttributeError, which the rule-set export's `except OSError` lets
    # through as a traceback instead of a message.
    monkeypatch.setattr(userfs, "IS_LINUX", False)
    monkeypatch.setattr(userfs, "IS_MAC", False)
    monkeypatch.delattr(userfs.os, "O_NOFOLLOW", raising=False)
    target = tmp_path / "rules.json"
    userfs.save_for_user(target, b'{"remarks": "x"}\n')
    assert target.read_bytes() == b'{"remarks": "x"}\n'


def test_userfs_refuses_outright_on_a_non_linux_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(userfs, "IS_LINUX", False)
    monkeypatch.setattr(userfs, "IS_MAC", False)
    with pytest.raises(userfs.UserFsError, match="Linux"):
        userfs.write_as_user(tmp_path / "x", b"x", uid=os.getuid(), gid=os.getgid())
    with pytest.raises(userfs.UserFsError, match="Linux"):
        userfs.unlink_as_user(tmp_path / "x", uid=os.getuid(), gid=os.getgid())


def test_save_for_user_completes_short_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(userfs, "invoking_user_ids", lambda: None)
    write = os.write
    monkeypatch.setattr(userfs.os, "write", lambda fd, data: write(fd, data[:3]))
    target = tmp_path / "پشتیبان 🚀.json"
    payload = 'سرور تهران'.encode()
    userfs.save_for_user(target, payload)
    assert target.read_bytes() == payload


def test_save_for_user_reports_a_zero_length_write(monkeypatch, tmp_path):
    monkeypatch.setattr(userfs, "invoking_user_ids", lambda: None)
    monkeypatch.setattr(userfs.os, "write", lambda fd, data: 0)
    with pytest.raises(OSError):
        userfs.save_for_user(tmp_path / "backup", b"must not disappear")


def test_unicode_paths_and_symlinked_parents_stay_with_the_user(tmp_path):
    directory = tmp_path / "کاربر 🚀"
    directory.mkdir()
    parent = tmp_path / "alias"
    parent.symlink_to(directory, target_is_directory=True)
    target = parent / "new" / "پشتیبان"
    userfs.write_as_user(target, b"content", os.getuid(), os.getgid())
    assert target.read_bytes() == b"content"
    assert target.stat().st_uid == os.getuid()
    assert target.stat().st_gid == os.getgid()


# --- write_private_as_user --------------------------------------------------

def test_write_private_as_user_writes_0600_file(tmp_path):
    dest = tmp_path / "secret.json"
    userfs.write_private_as_user(dest, b"top secret", os.getuid(), os.getgid())
    assert dest.read_bytes() == b"top secret"
    assert oct(dest.stat().st_mode & 0o777) == "0o600"


def test_write_private_as_user_overwrites_existing_longer_file(tmp_path):
    dest = tmp_path / "secret.json"
    dest.write_text("much longer old content", encoding="utf-8")
    userfs.write_private_as_user(dest, b"new", os.getuid(), os.getgid())
    assert dest.read_bytes() == b"new"
    assert oct(dest.stat().st_mode & 0o777) == "0o600"


def test_write_private_as_user_creates_missing_parent_directories(tmp_path):
    dest = tmp_path / "a" / "b" / "secret.json"
    userfs.write_private_as_user(dest, b"x", os.getuid(), os.getgid())
    assert dest.read_bytes() == b"x"
    assert oct(dest.stat().st_mode & 0o777) == "0o600"


def test_write_private_as_user_refuses_symlinked_destination(tmp_path):
    real_target = tmp_path / "real_secret.txt"
    real_target.write_text("original", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real_target)

    with pytest.raises(userfs.UserFsError):
        userfs.write_private_as_user(link, b"attacker data",
                                     os.getuid(), os.getgid())

    assert real_target.read_text(encoding="utf-8") == "original"
    assert link.is_symlink()


def test_write_private_as_user_refuses_symlinked_parent(tmp_path):
    real_dir = tmp_path / "realdir"
    real_dir.mkdir()
    (real_dir / "victim.json").write_text("{}", encoding="utf-8")
    link_dir = tmp_path / "linkdir"
    link_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(userfs.UserFsError):
        userfs.write_private_as_user(link_dir / "victim.json", b"x",
                                     os.getuid(), os.getgid())
    assert (real_dir / "victim.json").read_text(encoding="utf-8") == "{}"


def test_write_private_as_user_refuses_directory_destination(tmp_path):
    directory = tmp_path / "adir"
    directory.mkdir()
    with pytest.raises(userfs.UserFsError):
        userfs.write_private_as_user(directory, b"x", os.getuid(), os.getgid())


def test_write_private_as_user_failure_preserves_old_file_and_cleans_temp(
        tmp_path, monkeypatch):
    dest = tmp_path / "secret.json"
    dest.write_text("keep me", encoding="utf-8")

    real_run = userfs._run_as_user

    def flaky(argv, uid, gid, **kwargs):
        if argv[0].endswith("dd"):
            raise userfs.UserFsError("disk full")
        return real_run(argv, uid, gid, **kwargs)

    monkeypatch.setattr(userfs, "_run_as_user", flaky)
    with pytest.raises(userfs.UserFsError):
        userfs.write_private_as_user(dest, b"new secret",
                                     os.getuid(), os.getgid())
    # Old destination untouched, no temp file left behind.
    assert dest.read_text(encoding="utf-8") == "keep me"
    assert [p.name for p in tmp_path.iterdir()] == ["secret.json"]


def test_write_private_as_user_never_exposes_0644(tmp_path, monkeypatch):
    # Record the mode of every file that exists in the directory at each
    # step; the secret must never be present at a mode wider than 0600.
    dest = tmp_path / "secret.json"
    observed = []
    real_run = userfs._run_as_user

    def spy(argv, uid, gid, **kwargs):
        result = real_run(argv, uid, gid, **kwargs)
        for p in tmp_path.iterdir():
            observed.append((p.name, p.stat().st_mode & 0o777))
        return result

    monkeypatch.setattr(userfs, "_run_as_user", spy)
    userfs.write_private_as_user(dest, b"secret bytes",
                                 os.getuid(), os.getgid())
    # Every temp file that appeared must have been 0600 the whole time.
    for name, mode in observed:
        if name.startswith(".private."):
            assert mode == 0o600, f"temp {name} was 0{mode:o}"
    assert oct(dest.stat().st_mode & 0o777) == "0o600"


def test_write_private_as_user_order_and_mode(tmp_path, monkeypatch):
    # Mock the runner to assert the exact call order and that the temp is
    # created (0600) before dd writes any bytes.
    calls = []
    dest = tmp_path / "secret.json"

    def fake_run(argv, uid, gid, **kwargs):
        calls.append(argv)
        if argv[0].endswith("mktemp"):
            return b"/private/tmp/fake/.private.ABC123\n"
        return b""

    monkeypatch.setattr(userfs, "_run_as_user", fake_run)
    monkeypatch.setattr(userfs.shutil, "which",
                        lambda name, path=None: f"/usr/bin/{name}")
    userfs.write_private_as_user(dest, b"data", 1234, 5678)
    tools = [Path(argv[0]).name for argv in calls]
    assert tools == ["mkdir", "test", "mktemp", "dd", "mv"]
    # dd must target the private temp, not the destination.
    dd_argv = calls[3]
    assert any("of=/private/tmp/fake/.private.ABC123" in a for a in dd_argv)
    # mv must move the temp onto the destination.
    mv_argv = calls[4]
    assert "/private/tmp/fake/.private.ABC123" in mv_argv
    assert str(dest) in mv_argv


def test_write_private_as_user_no_shell_interpolation(tmp_path, monkeypatch):
    # A path with shell metacharacters must be passed as a single argv
    # element, never through a shell.
    calls = []

    def fake_run(argv, uid, gid, **kwargs):
        calls.append(argv)
        if argv[0].endswith("mktemp"):
            return b"/private/tmp/fake/.private.ABC123\n"
        return b""

    monkeypatch.setattr(userfs, "_run_as_user", fake_run)
    monkeypatch.setattr(userfs.shutil, "which",
                        lambda name, path=None: f"/usr/bin/{name}")
    dest = tmp_path / "$(rm -rf ~)" / "secret.json"
    userfs.write_private_as_user(dest, b"data", 1234, 5678)
    # No call may invoke a shell.
    for argv in calls:
        assert Path(argv[0]).name not in ("sh", "bash", "zsh")
    # The destination path appears verbatim as one argv element.
    assert str(dest) in calls[4]
