"""Back up and restore settings/profiles/subscriptions as a zip.

Excludes geo/ (re-downloadable), state/ and the runtime config (live
connection state -- restoring it would point a route/DNS backup at
reality that no longer matches) and logs. The backup holds server
passwords in the clear, same as settings.json/profiles/*.json already
do on disk; callers must warn about that before writing one.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from .. import __version__, paths
from . import userfs

IS_LINUX = sys.platform.startswith("linux")

# The exact set of names a restore will ever accept -- anything else in the
# zip (an absolute path, "..", or a file this app never wrote) is rejected
# outright rather than extracted, so a malicious or corrupt zip can't write
# outside base_dir() (zip-slip) or smuggle in an unrelated file.
_FIXED_NAMES = frozenset({
    "settings.json",
    "profiles/active.txt",
    "profiles/subscriptions.json",
    "profile_stats.json",
})

# Profile uids are uuid4().hex (32 lowercase hex chars); this is
# deliberately tighter than "no slash", since on Windows a name like
# "a\\..\\..\\evil.json" contains no forward slash at all and would
# resolve outside base_dir() once joined onto it with backslashes intact.
_PROFILE_MEMBER_RE = re.compile(r"^profiles/[A-Za-z0-9_-]{1,64}\.json$")

_MAX_MEMBER_BYTES = 20 * 1024 * 1024
_MAX_TOTAL_BYTES = 100 * 1024 * 1024


def _is_allowed_member(name: str) -> bool:
    return name in _FIXED_NAMES or bool(_PROFILE_MEMBER_RE.match(name))


def _profile_json_files() -> list[Path]:
    pdir = paths.profiles_dir()
    if not pdir.exists():
        return []
    return [p for p in pdir.glob("*.json") if p.name != "subscriptions.json"]


def _manifest() -> dict:
    return {"app": "sushTun", "version": __version__, "created": time.time()}


def backup(dest_zip: Path) -> None:
    # Reads happen as whatever this process already is (root, when
    # elevated) from base_dir()/profiles_dir(), which this app owns --
    # only the destination is a path the invoking user chose (a save
    # dialog), so only the write of the finished bytes needs to happen as
    # that user rather than as root.
    base = paths.base_dir()
    pdir = paths.profiles_dir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(_manifest(), indent=2))
        settings_path = base / "settings.json"
        if settings_path.exists():
            zf.write(settings_path, "settings.json")
        active = pdir / "active.txt"
        if active.exists():
            zf.write(active, "profiles/active.txt")
        subs = pdir / "subscriptions.json"
        if subs.exists():
            zf.write(subs, "profiles/subscriptions.json")
        for p in _profile_json_files():
            zf.write(p, f"profiles/{p.name}")
        stats = base / "profile_stats.json"
        if stats.exists():
            zf.write(stats, "profile_stats.json")
    data = buf.getvalue()

    ids = _real_user_ids()
    if ids is not None:
        userfs.write_as_user(dest_zip, data, *ids)
    else:
        fd = os.open(str(dest_zip), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


def _real_user_ids() -> tuple[int, int] | None:
    """On Linux, when running elevated (root via pkexec/sudo), the uid/gid
    of the user who invoked it -- so the backup can be written as them
    instead of as root writing into a path they control."""
    if not IS_LINUX or os.geteuid() != 0:
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


def restore(src_zip: Path) -> None:
    """Replace settings/profiles/subscriptions from `src_zip`. Raises
    ValueError for anything wrong with the archive itself -- a bad zip, a
    missing/foreign manifest, an unexpected member name, an oversized
    member, or a corrupt JSON file -- and changes nothing on disk when it
    does. Every member is read and validated before the first byte is
    written for real.
    """
    try:
        zf = zipfile.ZipFile(src_zip)
    except zipfile.BadZipFile as e:
        raise ValueError("not a valid zip file") from e

    base = paths.base_dir()
    resolved_base = base.resolve()

    with zf:
        names = zf.namelist()
        if "manifest.json" not in names:
            raise ValueError("not a sushTun backup (no manifest)")
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except ValueError as e:
            raise ValueError("not a sushTun backup (corrupt manifest)") from e
        if not isinstance(manifest, dict) or manifest.get("app") != "sushTun":
            raise ValueError("not a sushTun backup")

        payload: dict[str, bytes] = {}
        total_bytes = 0
        for name in names:
            if name == "manifest.json":
                continue
            if not _is_allowed_member(name):
                raise ValueError(f"unexpected file in backup: {name}")
            # A forged .zip can declare any size in its central directory;
            # reject the obviously-a-bomb case before ever calling read(),
            # which decompresses the full member into memory.
            info = zf.getinfo(name)
            if info.file_size > _MAX_MEMBER_BYTES:
                raise ValueError(f"backup is too large: {name}")
            total_bytes += info.file_size
            if total_bytes > _MAX_TOTAL_BYTES:
                raise ValueError("backup is too large")
            # Belt and braces alongside the member-name pattern above: even
            # a name the regex allowed must still land inside base_dir()
            # once actually joined and resolved.
            dest = (base / name).resolve()
            if resolved_base not in dest.parents:
                raise ValueError(f"unexpected file in backup: {name}")
            data = zf.read(name)
            if name.endswith(".json"):
                json.loads(data)  # raises ValueError on corruption
            payload[name] = data

    pdir = paths.profiles_dir()
    pdir.mkdir(parents=True, exist_ok=True)

    # Now that everything is validated, write for real: one atomic
    # replace per file (tmp file in the same directory + os.replace), so
    # a crash mid-restore never leaves a half-written file where a good
    # one used to be.
    written: set[Path] = set()
    for name, data in payload.items():
        dest = base / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent))
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, dest)
        written.add(dest)

    # A restore replaces the server list wholesale: drop any profile that
    # was not part of the backup.
    for old in _profile_json_files():
        if old not in written:
            old.unlink()
    if "profiles/active.txt" not in payload:
        (pdir / "active.txt").unlink(missing_ok=True)
