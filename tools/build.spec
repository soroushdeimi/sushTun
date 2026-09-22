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

# The theme loads its checkbox glyph by path next to theme.py; without it every
# checkbox in the packaged app drew no check mark.
for _svg in sorted((ROOT / "xrayui" / "ui").glob("*.svg")):
    datas.append((str(_svg), "xrayui/ui"))

# The Persian UI needs Vazirmatn; the system fallback has much taller metrics.
_fonts = ROOT / "assets" / "fonts"
if _fonts.is_dir():
    for _font in sorted(_fonts.glob("*.ttf")):
        datas.append((str(_font), "assets/fonts"))

ico = ROOT / "assets" / "icon.ico"
exe_icon = str(ico) if ico.exists() else None

a = Analysis(
    [str(ROOT / "app_main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["cv2", "segno"],
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
        # The Windows installer packages this tree too, and an installed
        # sushTun needs the same elevation the portable one asks for.
        uac_admin=IS_WIN,
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
        name="sushTun",
        console=False,
        uac_admin=IS_WIN,
        upx=False,
        icon=exe_icon,
    )
