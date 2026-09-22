"""Check GitHub releases for a newer sushTun, then download and install it.

The check is deliberately unobtrusive -- it runs in the background and any
failure at all is swallowed. Installing is the opposite: it only ever happens
because the user pressed a button, it reports every failure, and it refuses to
put anything in place that does not match the checksum published with the
release.

What "install" means depends on how this copy was installed:

  portable (Windows, Linux, macOS)  replace the executable in place, relaunch
  installed (Windows)               run the downloaded Inno Setup installer
  installed (Linux, the .deb)       nothing -- dpkg owns /opt/sushtun, and
                                    overwriting files inside an installed
                                    package leaves it inconsistent, so those
                                    builds are pointed at the release page

A note on trust: the checksum comes from the same release as the download, so
it catches a truncated, corrupted or mirror-mangled file, not a GitHub account
that has been taken over. Real protection against that needs a signing key the
project does not have; this is the honest limit of what is checked here.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__, paths
from . import proc

_API_URL = "https://api.github.com/repos/soroushdeimi/sushTun/releases/latest"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Every release publishes this next to the binaries: `sha256  filename` lines,
# the format sha256sum writes.
CHECKSUMS = "SHA256SUMS"

# Matches the artifact names in .github/workflows/release.yml.
PORTABLE_ASSETS = {"win32": "sushTun-windows.exe", "darwin": "sushTun-macos"}
PORTABLE_LINUX = "sushTun-linux"
SETUP_ASSET = "sushTun-Setup-{version}.exe"

# A download that came up this short is an error page, not a build.
_MIN_SIZE = 2 * 1024 * 1024
_CHUNK = 256 * 1024

# The renamed-aside previous executable, deleted on the next launch. Windows
# will not overwrite a running .exe but is perfectly happy to rename it, which
# is what makes replacing ourselves possible at all.
OLD_SUFFIX = ".old"


class UpdateError(Exception):
    """Something went wrong while downloading or installing -- always shown."""


@dataclass(frozen=True)
class Release:
    tag: str
    url: str  # the release page, for "what's new" and as the manual fallback
    notes: str = ""
    assets: dict[str, str] = field(default_factory=dict)  # name -> download url

    @property
    def version(self) -> str:
        """The tag without its leading v, as the installer file name spells it."""
        return self.tag[1:] if self.tag.startswith("v") else self.tag


def _default_fetch() -> dict:
    req = urllib.request.Request(
        _API_URL, headers={"User-Agent": f"sushTun/{__version__}"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (GitHub's own API)
        return json.loads(resp.read().decode("utf-8"))


def latest_release(fetch: Callable[[], dict] | None = None) -> Release | None:
    """The latest GitHub release, or None on any failure at all -- a flaky
    network, a GitHub outage, or a malformed response must never raise; a
    background update check is not something that should ever surface as an
    error to the user."""
    fetch = fetch or _default_fetch
    try:
        data = fetch()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tag, url = data.get("tag_name"), data.get("html_url")
    if not isinstance(tag, str) or not tag or not isinstance(url, str) or not url:
        return None
    assets = {}
    for item in data.get("assets") or []:
        if not isinstance(item, dict):
            continue
        name, href = item.get("name"), item.get("browser_download_url")
        if isinstance(name, str) and name and isinstance(href, str) and href:
            assets[name] = href
    notes = data.get("body")
    return Release(tag=tag, url=url, notes=notes if isinstance(notes, str) else "",
                   assets=assets)


def is_newer(tag: str, current: str) -> bool:
    """True when `tag` (e.g. "v0.2.0") is a numeric release newer than
    `current` (e.g. "0.1.13"). A non-numeric or pre-release tag (a draft,
    "-rc1", "-beta") is never treated as newer, so it never nags a user
    who is already caught up.
    """
    tag_m = _VERSION_RE.match(tag.strip())
    cur_m = _VERSION_RE.match(current.strip())
    if not tag_m or not cur_m:
        return False
    return tuple(map(int, tag_m.groups())) > tuple(map(int, cur_m.groups()))


# -- what this particular copy can install ---------------------------------

def installed_windows() -> bool:
    """A Windows copy put there by the installer, rather than a portable exe."""
    return IS_WIN and paths.installed()


def installed_deb() -> bool:
    """The Linux .deb. dpkg owns those files; replacing them behind its back
    leaves the package database describing a version that is no longer there."""
    return not IS_WIN and not IS_MAC and paths.installed()


def asset_for_this_build(release: Release) -> str | None:
    """The release asset this copy should install, or None when it cannot
    install anything itself and the user has to be sent to the release page."""
    if not getattr(sys, "frozen", False):
        return None  # a source checkout updates with git, not with a binary
    if installed_deb():
        return None
    name = (SETUP_ASSET.format(version=release.version) if installed_windows()
            else PORTABLE_ASSETS.get(sys.platform, PORTABLE_LINUX))
    return name if name in release.assets else None


# -- downloading -----------------------------------------------------------

Progress = Callable[[int, int], None]     # bytes so far, total (0 = unknown)
Cancelled = Callable[[], bool]


def _read_url(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"sushTun/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def _stream_url(url: str, dest: Path, on_progress: Progress | None,
                cancelled: Cancelled | None, timeout: float = 60.0) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": f"sushTun/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with dest.open("wb") as out:
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateError("cancelled")
                try:
                    chunk = resp.read(_CHUNK)
                except http.client.IncompleteRead as exc:
                    raise UpdateError(f"download incomplete: {exc}") from exc
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)
    if total and done != total:
        # Every byte arrived as far as read() was concerned, but not as many as
        # the server promised: a lying proxy, or a connection cut cleanly.
        raise UpdateError(f"download incomplete: got {done} bytes, expected {total}")


def parse_checksums(text: str) -> dict[str, str]:
    """`sha256  filename` lines into {filename: sha256}, sha256sum's format.

    The name may carry a `*` binary marker, and unrelated lines are ignored so
    a release that grows a header or a comment does not break updating."""
    out = {}
    for line in text.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts[0].strip().lower(), parts[1].strip().lstrip("*")
        if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest) and name:
            out[name] = digest
    return out


def _expected_digest(release: Release, name: str) -> str:
    url = release.assets.get(CHECKSUMS)
    if not url:
        raise UpdateError(f"the release publishes no {CHECKSUMS} to check the download against")
    try:
        text = _read_url(url, timeout=30).decode("utf-8", errors="replace")
    except OSError as exc:
        raise UpdateError(f"could not fetch {CHECKSUMS}: {exc}") from exc
    digest = parse_checksums(text).get(name)
    if not digest:
        raise UpdateError(f"{CHECKSUMS} does not list {name}")
    return digest


def _staging_dir() -> Path:
    """Somewhere to download to.

    Next to the executable when we mean to replace it, because os.replace
    cannot move a file across volumes and %TEMP% is very often a different
    one. The installer path does not care, so it uses the system temp
    directory and leaves the install directory alone."""
    if installed_windows():
        return Path(tempfile.mkdtemp(prefix="sushtun-update-"))
    staging = paths.base_dir() / "update.tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    return staging


def download(release: Release, on_progress: Progress | None = None,
             cancelled: Cancelled | None = None) -> Path:
    """Fetch this build's asset, verify it, and return where it landed.

    Raises UpdateError with a short reason and leaves nothing behind on any
    failure, cancellation included."""
    name = asset_for_this_build(release)
    if not name:
        raise UpdateError("this build cannot update itself")
    digest = _expected_digest(release, name)

    staging = _staging_dir()
    dest = staging / name
    try:
        _stream_url(release.assets[name], dest, on_progress, cancelled)
        size = dest.stat().st_size
        if size < _MIN_SIZE:
            raise UpdateError(f"the download looks truncated ({size} bytes)")
        actual = sha256_file(dest)
        if actual != digest:
            raise UpdateError("the download does not match the checksum in the release")
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(str(exc)) from exc
    return dest


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


# -- installing ------------------------------------------------------------

def install(downloaded: Path) -> None:
    """Put the download in place. The caller quits the app straight afterwards.

    On Windows this is the last moment the old executable exists: it has been
    renamed aside by the time this returns."""
    if installed_windows():
        _run_installer(downloaded)
    else:
        _replace_executable(downloaded)


def _run_installer(setup: Path) -> None:
    """Hand over to Inno Setup's own installer.

    /SILENT still shows a progress window, which is the only sign the user
    gets that anything is happening once sushTun has quit. CLOSEAPPLICATIONS
    and RESTARTAPPLICATIONS let the restart manager close this process and
    bring it back on the new version."""
    try:
        subprocess.Popen(  # noqa: S603 (our own download, checksum-verified)
            [str(setup), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS",
             "/RESTARTAPPLICATIONS"],
            creationflags=proc.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except OSError as exc:
        raise UpdateError(f"could not start the installer: {exc}") from exc


def _replace_executable(new: Path) -> None:
    """Swap the running executable for the download.

    Windows refuses to overwrite a running .exe but will rename it, so the old
    one is moved aside and deleted on the next launch. POSIX keeps the running
    inode alive through a rename, so there the old name can simply go."""
    target = Path(sys.executable).resolve()
    aside = target.with_name(target.name + OLD_SUFFIX)
    try:
        _copy_attributes(target, new)
        if aside.exists():
            aside.unlink()
        os.replace(target, aside)
    except OSError as exc:
        raise UpdateError(f"could not move the current version aside: {exc}") from exc
    try:
        os.replace(new, target)
    except OSError as exc:
        # Put the working copy back rather than leave no executable at all.
        try:
            os.replace(aside, target)
        except OSError:
            pass
        raise UpdateError(f"could not put the new version in place: {exc}") from exc
    if not IS_WIN:
        aside.unlink(missing_ok=True)


def _copy_attributes(current: Path, new: Path) -> None:
    """Give the download the mode and owner the current executable has.

    sushTun runs elevated, so a file it writes is root-owned; without this a
    portable copy living in a user's home would come back owned by root and
    could no longer be started, or deleted, without a password."""
    try:
        info = current.stat()
    except OSError:
        return
    try:
        new.chmod(stat.S_IMODE(info.st_mode))
        if not IS_WIN:
            os.chown(new, info.st_uid, info.st_gid)
    except (OSError, AttributeError):
        pass


def clean_previous() -> None:
    """Delete the executable left behind by the last update.

    Called at startup: Windows only frees the old name once the process using
    it has gone, which is exactly one launch ago."""
    if not getattr(sys, "frozen", False):
        return
    try:
        target = Path(sys.executable).resolve()
        target.with_name(target.name + OLD_SUFFIX).unlink(missing_ok=True)
        shutil.rmtree(paths.base_dir() / "update.tmp", ignore_errors=True)
    except OSError:
        pass  # a leftover file is untidy, never a reason to fail a launch


# Waiting for this process to go before starting the new one: sushTun allows
# one copy per machine (ui/single_instance.py), so a new one started too early
# would simply hand its window to the old one and exit. Quitting also tears the
# tunnel down, which must finish before anything reconfigures the network again.
_WAIT_PS = (
    "Wait-Process -Id $env:SUSHTUN_PID -Timeout 120 -ErrorAction SilentlyContinue; "
    "Start-Sleep -Milliseconds 800; "
    "Start-Process -FilePath $env:SUSHTUN_EXE"
)
_WAIT_SH = (
    'while kill -0 "$SUSHTUN_PID" 2>/dev/null; do sleep 0.3; done; '
    'sleep 0.8; exec "$SUSHTUN_EXE"'
)


def relaunch_after_exit() -> bool:
    """Arrange for the new executable to start once this process has quit.

    Not used after the Windows installer, which restarts sushTun itself."""
    target = Path(sys.executable).resolve()
    env = {"SUSHTUN_EXE": str(target), "SUSHTUN_PID": str(os.getpid())}
    try:
        if IS_WIN:
            subprocess.Popen(  # noqa: S603
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WAIT_PS],
                env=proc.child_env(env),
                creationflags=proc.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            )
        else:
            subprocess.Popen(  # noqa: S603
                ["/bin/sh", "-c", _WAIT_SH],
                env=proc.child_env(env), start_new_session=True,
            )
    except OSError:
        return False
    return True
