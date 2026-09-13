"""Write files as the real (non-root) user, not as root.

core/autostart.py and core/backup.py run as root (via pkexec/sudo) but
write into paths the invoking user fully controls: ~/.config/autostart,
or wherever a save dialog points. A local user can pre-create any of
those as a symlink to a root-owned file (e.g. /etc/shadow) or make a
parent directory itself a symlink; if root wrote there and then chowned
the result to the user, that is a straight root-write + hand-the-result-
to-the-attacker escalation.

Dropping to the user's own uid/gid before the write lets the kernel's
own permission checks do the enforcing instead: if the symlink points
somewhere that user couldn't write anyway, the write fails there too,
exactly as if the user had run it themselves. Since the file ends up
created by the user in the first place, no chown is ever needed.
"""
from __future__ import annotations

import os
from pathlib import Path


class UserFsError(RuntimeError):
    pass


def _run_as(uid: int, gid: int, fn) -> None:
    # A forked child either fully becomes the user or dies without
    # touching anything -- a failed setuid/setgid can never leave this
    # (still-root) process holding an open fd or a half-done write.
    pid = os.fork()
    if pid == 0:
        try:
            # Only root can actually drop privilege; a non-root caller
            # (an unprivileged test, or a non-elevated code path) is
            # already running as the target user, so there is nothing to
            # drop and setgroups()/setgid()/setuid() would just raise.
            if os.geteuid() == 0:
                os.setgroups([])
                os.setgid(gid)
                os.setuid(uid)
                if os.getuid() != uid or os.getgid() != gid:
                    os._exit(1)
            fn()
        except Exception:
            os._exit(1)
        os._exit(0)
        return
    _, status = os.waitpid(pid, 0)
    if not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0):
        raise UserFsError(f"operation failed running as uid {uid}")


def _mkdirs(path: Path) -> None:
    # A directory symlink in the path (e.g. ~/.config/autostart -> /etc) is
    # still followed here, same as any normal mkdir -p would -- but every
    # operation below runs as the target uid/gid, so following it can only
    # ever reach what that user could already write to themselves. That,
    # not blanket symlink rejection, is what makes root safe to call this.
    if path.exists():
        return
    _mkdirs(path.parent)
    os.mkdir(str(path), 0o755)  # raises if a symlink or file already sits here


def write_as_user(path: Path, data: bytes, uid: int, gid: int, mode: int = 0o644) -> None:
    """Write `data` to `path` as uid/gid. Refuses to follow a symlink at
    `path` itself; parent directories are created (never followed through
    an existing symlink, since os.mkdir on one raises FileExistsError)."""
    def do() -> None:
        _mkdirs(path.parent)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    _run_as(uid, gid, do)


def unlink_as_user(path: Path, uid: int, gid: int, missing_ok: bool = True) -> None:
    def do() -> None:
        try:
            os.unlink(str(path))
        except FileNotFoundError:
            if not missing_ok:
                raise
    _run_as(uid, gid, do)
