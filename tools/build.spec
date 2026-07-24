# PyInstaller one-file spec. Build with:  pyinstaller tools/build.spec
from pathlib import Path

ROOT = Path(SPECPATH).parent

_ASSETS = ["config.template.json", "xray.exe", "geoip.dat", "geosite.dat", "wintun.dll"]
datas = [(str(ROOT / a), ".") for a in _ASSETS if (ROOT / a).exists()]

a = Analysis(
    [str(ROOT / "xrayui" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["cv2"],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="XrayPortable",
    console=False,
    uac_admin=True,
    upx=False,
)
