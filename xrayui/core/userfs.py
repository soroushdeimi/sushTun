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

This used to drop privilege with a raw os.fork() + setuid() inside this
process -- but this is a Qt app with background threads running the
moment it starts (LogTailer, QThreadPool), and CPython warns that
fork() from a multi-threaded process can leave the child wedged if
another thread held a lock (malloc's arena lock, import machinery, ...)
at the instant of the fork; the child still runs plenty of Python
(pathlib, exception handling) before exiting. The original code also
had no timeout on the parent's waitpid, so a wedged child would hang
forever the QThreadPool worker (or the UI thread, for Back up...)
calling it. subprocess.run() instead goes through CPython's own C-level
fork+exec helper, which is written to be safe from a multi-threaded
process, and it takes a hard timeout.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import proc

IS_LINUX = sys.platform.startswith("linux")

# Never the inherited PATH -- an elevated process's PATH could itself be
# attacker-influenced (a hijacked sudo/pkexec environment); every tool this
# module runs is resolved from this fixed, standard location instead.
_TOOL_PATH = "/usr/bin:/bin"


class UserFsError(RuntimeError):
    pass


def _require_linux() -> None:
    if not IS_LINUX:
        raise UserFsError("core.userfs is Linux-only")


def _tool(name: str) -> str:
    path = shutil.which(name, path=_TOOL_PATH)
    if path is None:
        raise UserFsError(f"required tool not found: {name}")
    return path


def _run_as_user(argv: list[str], uid: int, gid: int, *,
                 input: bytes | None = None, timeout: float = 10) -> None:
    kwargs: dict = {}
    if os.geteuid() == 0:
        # A non-root caller can't setgroups()/setgid()/setuid() at all, and
        # is already running as the target user -- nothing to drop.
        kwargs["user"] = uid
        kwargs["group"] = gid
        kwargs["extra_groups"] = []
    try:
        # argv[0] always comes from _tool()'s absolute-path resolution --
        # never a shell, never anything derived from unsanitized input.
        result = subprocess.run(
            argv,
            input=input,
            capture_output=True,
            timeout=timeout,
            env=proc.child_env({"PATH": _TOOL_PATH, "LC_ALL": "C"}),
            umask=0o022,
            **kwargs,
        )
    except subprocess.TimeoutExpired as e:
        raise UserFsError("timed out") from e
    if result.returncode != 0:
        lines = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise UserFsError(lines[-1] if lines else f"exit code {result.returncode}")


def write_as_user(path: Path, data: bytes, uid: int, gid: int, mode: int = 0o644) -> None:
    """Write `data` to `path` as uid/gid, truncating an existing regular
    file and refusing a symlink at `path` itself. Parent directories are
    created as that user too, so a symlinked parent can only ever be
    followed to wherever the user could already write themselves."""
    _require_linux()
    _run_as_user([_tool("mkdir"), "-p", "--", str(path.parent)], uid, gid)
    # oflag=nofollow: refuses to open `path` if it's a symlink. GNU dd
    # truncates the destination by default (conv=notrunc is what disables
    # that), so this is equivalent to O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW.
    _run_as_user([_tool("dd"), f"of={path}", "oflag=nofollow", "status=none"],
                 uid, gid, input=data)
    # umask alone can't guarantee a requested mode (it can only take bits
    # away), so this pins it exactly -- as the user, so it's safe to do.
    _run_as_user([_tool("chmod"), f"{mode:03o}", "--", str(path)], uid, gid)


def unlink_as_user(path: Path, uid: int, gid: int, missing_ok: bool = True) -> None:
    _require_linux()
    if not missing_ok:
        try:
            _run_as_user([_tool("test"), "-e", str(path)], uid, gid)
        except UserFsError as e:
            raise UserFsError(f"{path} does not exist") from e
    # rm removes a symlink itself; it never follows one to its target.
    _run_as_user([_tool("rm"), "-f", "--", str(path)], uid, gid)
