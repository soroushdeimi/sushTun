"""Back up and restore settings/profiles/subscriptions as a zip.

Excludes geo/ (re-downloadable), state/ and the runtime config (live
connection state -- restoring it would point a route/DNS backup at
reality that no longer matches) and logs. The backup holds server
passwords in the clear, same as settings.json/profiles/*.json already
do on disk; callers must warn about that before writing one.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from .. import __version__, paths

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


def _is_allowed_member(name: str) -> bool:
    if name in _FIXED_NAMES:
        return True
    if name.startswith("profiles/") and name.endswith(".json"):
        rest = name[len("profiles/"):]
        return bool(rest) and "/" not in rest and rest != ".." and not rest.startswith(".")
    return False


def _profile_json_files() -> list[Path]:
    pdir = paths.profiles_dir()
    if not pdir.exists():
        return []
    return [p for p in pdir.glob("*.json") if p.name != "subscriptions.json"]


def _manifest() -> dict:
    return {"app": "sushTun", "version": __version__, "created": time.time()}


def backup(dest_zip: Path) -> None:
    base = paths.base_dir()
    pdir = paths.profiles_dir()
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
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
    _chown_to_real_user(dest_zip)


def _chown_to_real_user(path: Path) -> None:
    """On Linux, when running elevated (root via pkexec/sudo), hand the
    freshly-written file back to the real user so they can open it."""
    if not IS_LINUX or os.geteuid() != 0:
        return
    uid_s = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    if not uid_s:
        return
    try:
        import pwd
        pw = pwd.getpwuid(int(uid_s))
        os.chown(path, pw.pw_uid, pw.pw_gid)
    except (ValueError, KeyError, OSError):
        pass


def restore(src_zip: Path) -> None:
    """Replace settings/profiles/subscriptions from `src_zip`. Raises
    ValueError for anything wrong with the archive itself -- a bad zip, a
    missing/foreign manifest, an unexpected member name, or a corrupt
    JSON file -- and changes nothing on disk when it does. Every member
    is read and validated before the first byte is written for real.
    """
    try:
        zf = zipfile.ZipFile(src_zip)
    except zipfile.BadZipFile as e:
        raise ValueError("not a valid zip file") from e

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
        for name in names:
            if name == "manifest.json":
                continue
            if not _is_allowed_member(name):
                raise ValueError(f"unexpected file in backup: {name}")
            data = zf.read(name)
            if name.endswith(".json"):
                json.loads(data)  # raises ValueError on corruption
            payload[name] = data

    base = paths.base_dir()
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
