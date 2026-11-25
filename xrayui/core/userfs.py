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
IS_MAC = sys.platform == "darwin"

# Never the inherited PATH -- an elevated process's PATH could itself be
# attacker-influenced (a hijacked sudo/pkexec environment); every tool this
# module runs is resolved from this fixed, standard location instead.
_TOOL_PATH = "/usr/bin:/bin"


class UserFsError(RuntimeError):
    pass


def _require_supported() -> None:
    if not (IS_LINUX or IS_MAC):
        raise UserFsError("core.userfs is Linux and macOS only")


def _tool(name: str) -> str:
    path = shutil.which(name, path=_TOOL_PATH)
    if path is None:
        raise UserFsError(f"required tool not found: {name}")
    return path


def _run_as_user(argv: list[str], uid: int, gid: int, *,
                 input: bytes | None = None, timeout: float = 10) -> bytes:
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
    return result.stdout


def write_as_user(path: Path, data: bytes, uid: int, gid: int, mode: int = 0o644) -> None:
    """Write `data` to `path` as uid/gid, truncating an existing regular
    file and refusing a symlink at `path` itself. Parent directories are
    created as that user too, so a symlinked parent can only ever be
    followed to wherever the user could already write themselves."""
    _require_supported()
    _run_as_user([_tool("mkdir"), "-p", "--", str(path.parent)], uid, gid)
    # oflag=nofollow: refuses to open `path` if it's a symlink. GNU dd
    # truncates the destination by default (conv=notrunc is what disables
    # that), so this is equivalent to O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW.
    if IS_MAC:
        # BSD dd has no oflag=nofollow. Refuse the symlink up front instead:
        # the write runs as the user, so losing a race here can only reach
        # somewhere they could already write themselves.
        try:
            _run_as_user([_tool("test"), "!", "-L", str(path)], uid, gid)
        except UserFsError as e:
            raise UserFsError(f"refusing to write through a symlink at {path}") from e
        _run_as_user([_tool("dd"), f"of={path}", "status=none"], uid, gid, input=data)
    else:
        _run_as_user([_tool("dd"), f"of={path}", "oflag=nofollow", "status=none"],
                     uid, gid, input=data)
    # umask alone can't guarantee a requested mode (it can only take bits
    # away), so this pins it exactly -- as the user, so it's safe to do.
    if IS_MAC:
        # BSD chmod takes "--" only before the mode; after it, "--" is a file.
        _run_as_user([_tool("chmod"), "--", f"{mode:03o}", str(path)], uid, gid)
    else:
        _run_as_user([_tool("chmod"), f"{mode:03o}", "--", str(path)], uid, gid)


def write_private_as_user(path: Path, data: bytes, uid: int, gid: int) -> None:
    """Atomically write `data` to `path` as uid/gid, mode 0600.

    A temp file is created at 0600 *before* any bytes are written, so the
    secret is never exposed at a wider mode; the destination is replaced
    with rename(2), which never follows a symlink at `path`. On any
    failure the old destination is left untouched and the temp is removed.
    """
    _require_supported()
    path = Path(path)
    # Best-effort pre-check (not race-free for parents): refuse a directory
    # destination and a symlink at the destination or any parent. The final
    # component is re-checked as the user below, and mv(1) never follows it.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise UserFsError(f"refusing to follow a symlink at {part}")
    if path.is_dir():
        raise UserFsError(f"refusing to write a private file to a directory: {path}")
    _run_as_user([_tool("mkdir"), "-p", "--", str(path.parent)], uid, gid)
    try:
        _run_as_user([_tool("test"), "!", "-L", str(path)], uid, gid)
    except UserFsError as e:
        raise UserFsError(f"refusing to write through a symlink at {path}") from e
    # mktemp creates the file 0600 before any data is written to it.
    tmp = _run_as_user(
        [_tool("mktemp"), f"{path.parent}/.private.XXXXXX"], uid, gid
    ).decode("utf-8", "replace").strip()
    if not tmp:
        raise UserFsError("could not create a private temp file")
    try:
        _run_as_user([_tool("dd"), f"of={tmp}", "status=none"], uid, gid, input=data)
        # mv(1) is rename(2): it replaces a symlink at the destination
        # rather than following it, and keeps the temp's 0600 mode.
        _run_as_user([_tool("mv"), "-f", "--", tmp, str(path)], uid, gid)
    except BaseException:
        try:
            _run_as_user([_tool("rm"), "-f", "--", tmp], uid, gid)
        except UserFsError:
            pass
        raise


def unlink_as_user(path: Path, uid: int, gid: int, missing_ok: bool = True) -> None:
    _require_supported()
    if not missing_ok:
        try:
            _run_as_user([_tool("test"), "-e", str(path)], uid, gid)
        except UserFsError as e:
            raise UserFsError(f"{path} does not exist") from e
    # rm removes a symlink itself; it never follows one to its target.
    _run_as_user([_tool("rm"), "-f", "--", str(path)], uid, gid)


def invoking_user_ids() -> tuple[int, int] | None:
    """(uid, gid) of the user who elevated this process, or None when it is
    not elevated or cannot tell -- then a plain write is already theirs."""
    if not (IS_LINUX or IS_MAC) or os.geteuid() != 0:
        return None
    uid_s = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    if not uid_s:
        return None
    try:
        import pwd
        pw = pwd.getpwuid(int(uid_s))
        return pw.pw_uid, pw.pw_gid
    except (ValueError, KeyError):
        return None


def save_for_user(path: Path, data: bytes) -> None:
    """Write a file to a place the user chose (a save dialog), owned by them.

    Written by root, an exported file came out owned by root: the user could
    not overwrite or delete it again without an admin password.
    """
    ids = invoking_user_ids()
    if ids is not None:
        write_as_user(path, data, *ids)
        return
    # O_NOFOLLOW does not exist on Windows and O_BINARY exists only there, so
    # ask for whichever this platform has: naming either outright would raise
    # an AttributeError the callers' own `except OSError` does not catch, and
    # without O_BINARY Windows would rewrite the newlines of an exported file.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(str(path), flags, 0o644)
    try:
        remaining = memoryview(data)
        while remaining:
            written = os.write(fd, remaining)
            if written == 0:
                raise OSError("file write made no progress")
            remaining = remaining[written:]
    finally:
        os.close(fd)
