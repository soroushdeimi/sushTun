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


def test_userfs_refuses_outright_on_a_non_linux_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(userfs, "IS_LINUX", False)
    with pytest.raises(userfs.UserFsError, match="Linux"):
        userfs.write_as_user(tmp_path / "x", b"x", uid=os.getuid(), gid=os.getgid())
    with pytest.raises(userfs.UserFsError, match="Linux"):
        userfs.unlink_as_user(tmp_path / "x", uid=os.getuid(), gid=os.getgid())
