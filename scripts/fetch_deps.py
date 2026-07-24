#!/usr/bin/env python3
"""Fetch third-party redistributables for the current platform.

Pulls the matching Xray-core binary (XTLS/Xray-core), the enhanced
geoip.dat/geosite.dat routing data (Loyalsoldier/v2ray-rules-dat, which ships
ir/ru/cn plus win-spy/win-update/win-extra), and wintun.dll on Windows.
Cross-platform and stdlib-only so it runs in every CI runner.
"""
from __future__ import annotations

import io
import platform
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

XRAY_ASSETS = {
    ("windows", "64"): "Xray-windows-64.zip",
    ("darwin", "64"): "Xray-macos-64.zip",
    ("darwin", "arm64"): "Xray-macos-arm64-v8a.zip",
    ("linux", "64"): "Xray-linux-64.zip",
    ("linux", "arm64"): "Xray-linux-arm64-v8a.zip",
}
XRAY_URL = "https://github.com/XTLS/Xray-core/releases/latest/download/{}"
GEO_URL = "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/{}"
WINTUN_URL = "https://www.wintun.net/builds/wintun-0.14.1.zip"


def _os() -> str:
    return {"win32": "windows", "darwin": "darwin"}.get(sys.platform, "linux")


def _arch() -> str:
    return "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "64"


def _get(url: str) -> bytes:
    print(f"  GET {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def _download(url: str, dest: Path) -> None:
    dest.write_bytes(_get(url))


def _fetch_xray(os_name: str) -> None:
    asset = XRAY_ASSETS[(os_name, _arch())]
    data = _get(XRAY_URL.format(asset))
    binary = "xray.exe" if os_name == "windows" else "xray"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in ("xray.exe", "xray"):
            if name in zf.namelist():
                (ROOT / binary).write_bytes(zf.read(name))
                break
    if os_name != "windows":
        path = ROOT / binary
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _fetch_wintun() -> None:
    data = _get(WINTUN_URL)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        (ROOT / "wintun.dll").write_bytes(zf.read("wintun/bin/amd64/wintun.dll"))


def main() -> int:
    os_name = _os()
    force = "--force" in sys.argv
    print(f"Fetching dependencies for {os_name}/{_arch()} into {ROOT}")

    binary = "xray.exe" if os_name == "windows" else "xray"
    if force or not (ROOT / binary).exists():
        print("Xray-core...")
        _fetch_xray(os_name)

    for dat in ("geoip.dat", "geosite.dat"):
        if force or not (ROOT / dat).exists():
            print(f"{dat} (Loyalsoldier)...")
            _download(GEO_URL.format(dat), ROOT / dat)

    if os_name == "windows" and (force or not (ROOT / "wintun.dll").exists()):
        print("wintun.dll...")
        _fetch_wintun()

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
