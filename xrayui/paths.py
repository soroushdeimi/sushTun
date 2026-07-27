"""Portable path resolution for both frozen (PyInstaller) and source runs."""
from __future__ import annotations

import sys
from pathlib import Path


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    # Writable, persistent location: next to the exe, or the project root in dev.
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
