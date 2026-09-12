"""Portable path resolution for both frozen (PyInstaller) and source runs."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The .deb drops this marker next to the installed executable. /opt is not a
# place to write settings, so installed builds keep their data in a system
# directory instead (the app runs as root; profiles hold credentials).
INSTALLED_MARKER = ".installed"
INSTALLED_DATA_DIR = Path("/var/lib/sushtun")


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def installed() -> bool:
    return _frozen() and (Path(sys.executable).resolve().parent / INSTALLED_MARKER).exists()


def base_dir() -> Path:
    # Writable, persistent location: next to the exe, or the project root in dev.
    if installed():
        if os.geteuid() == 0:
            return INSTALLED_DATA_DIR
        # A refused password prompt still opens an unelevated window; give it
        # somewhere it may write instead of crashing on /var/lib.
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return Path(xdg) / "sushtun"
    if _frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    # Read-only bundled assets: _MEIPASS when frozen, project root otherwise.
    if _frozen():
        return Path(getattr(sys, "_MEIPASS", base_dir()))
    return base_dir()


def _first_existing(name: str) -> Path:
    for root in (resource_dir(), base_dir()):
        p = root / name
        if p.exists():
            return p
    return base_dir() / name


def xray_exe() -> Path:
    return _first_existing("xray.exe" if sys.platform == "win32" else "xray")


def tun2socks_bin() -> Path:
    # macOS only: Xray has no native TUN inbound there, so tun2socks bridges
    # its SOCKS inbound to a real TUN device.
    return _first_existing("tun2socks")


def config_template() -> Path:
    """The Xray config template.

    A copy placed next to the exe wins over the bundled one, so config can be
    changed in the field without a rebuild-and-release cycle. In a source run
    the two directories are the same and this is a no-op.
    """
    override = base_dir() / "config.template.json"
    if override.exists():
        return override
    return _first_existing("config.template.json")


def asset_dir() -> Path:
    """Directory holding geoip.dat / geosite.dat (XRAY_LOCATION_ASSET)."""
    return _first_existing("geoip.dat").parent


def icon_png() -> Path:
    return _first_existing("assets/icon.png")


def icon_ico() -> Path:
    return _first_existing("assets/icon.ico")


def runtime_config() -> Path:
    return base_dir() / "config.runtime.json"


def log_file() -> Path:
    return base_dir() / "xray.log"


def state_dir() -> Path:
    return base_dir() / "state"


def profiles_dir() -> Path:
    return base_dir() / "profiles"


def ensure_dirs() -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    profiles_dir().mkdir(parents=True, exist_ok=True)
