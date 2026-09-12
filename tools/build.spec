# PyInstaller one-file spec (cross-platform). Build with: pyinstaller tools/build.spec
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
# SUSHTUN_ONEDIR=1 builds the unpacked dist/sushtun/ tree the .deb installs
# (scripts/build_deb.py). It starts at once, where the one-file build re-extracts
# its ~170 MB into /tmp on every launch.
ONEDIR = os.environ.get("SUSHTUN_ONEDIR") == "1"

xray_bin = "xray.exe" if IS_WIN else "xray"
_ASSETS = ["config.template.json", "geoip.dat", "geosite.dat", xray_bin]
if IS_WIN:
    _ASSETS.append("wintun.dll")
if IS_MAC:
    _ASSETS.append("tun2socks")
datas = [(str(ROOT / a), ".") for a in _ASSETS if (ROOT / a).exists()]
for _icon in ("assets/icon.png", "assets/icon.ico"):
    if (ROOT / _icon).exists():
        datas.append((str(ROOT / _icon), "assets"))

ico = ROOT / "assets" / "icon.ico"
exe_icon = str(ico) if ico.exists() else None

a = Analysis(
    [str(ROOT / "app_main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["cv2"],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONEDIR:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="sushtun",
        console=False,
        upx=False,
        icon=exe_icon,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="sushtun", upx=False)
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="XrayPortable",
        console=False,
        uac_admin=IS_WIN,
        upx=False,
        icon=exe_icon,
    )
