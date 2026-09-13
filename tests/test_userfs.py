"""userfs: privilege-drop file writes, and the symlink they must refuse.

Runs unprivileged (uid == gid == the test's own): userfs only actually
drops privilege when the caller is root (os.geteuid() == 0), so under a
normal test run these exercise the exact same fork + O_NOFOLLOW code
path with no-op identity, which is enough to prove the one thing that
never depends on privilege -- a symlinked destination is refused.
"""
from __future__ import annotations

import os

import pytest

from xrayui.core import userfs


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


def test_write_as_user_creates_missing_parent_directories(tmp_path):
    dest = tmp_path / "a" / "b" / "out.txt"
    userfs.write_as_user(dest, b"x", uid=os.getuid(), gid=os.getgid())
    assert dest.read_bytes() == b"x"


def test_write_as_user_overwrites_an_existing_regular_file(tmp_path):
    dest = tmp_path / "out.txt"
    dest.write_text("old", encoding="utf-8")
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
