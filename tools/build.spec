# PyInstaller one-file spec (cross-platform). Build with: pyinstaller tools/build.spec
import os
import re
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

# Exit-country flags and their names, looked up by country code at runtime.
_flags = ROOT / "assets" / "flags"
if _flags.is_dir():
    for _pattern in ("*.svg", "*.json", "LICENSE-*"):
        for _flag in sorted(_flags.glob(_pattern)):
            datas.append((str(_flag), "assets/flags"))

ico = ROOT / "assets" / "icon.ico"
exe_icon = str(ico) if ico.exists() else None
# Written into the .app's Info.plist, so Finder and "About" show the real
# version instead of 0.0.0. Read, not imported: the spec runs before the
# package is importable.
_init = (ROOT / "xrayui" / "__init__.py").read_text(encoding="utf-8")
_m = re.search(r'__version__\s*=\s*"([^"]+)"', _init)
VERSION = _m.group(1) if _m else "0.0.0"

a = Analysis(
    [str(ROOT / "app_main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["cv2", "segno"],
    excludes=[
        "tkinter",
        # Qt bindings nothing imports (only QtCore/QtGui/QtWidgets/QtNetwork/
        # QtSvg are ever imported). This stops their Python shims; the
        # frameworks/plugins below are filtered out of the collected files.
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtQmlModels", "PySide6.QtQmlWorkerScript",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtVirtualKeyboard", "PySide6.QtVirtualKeyboardSettings",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtXml",
        "PySide6.QtDesigner", "PySide6.QtHelp",
        "PySide6.QtBluetooth", "PySide6.QtNfc",
        "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort",
        "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtWebSockets", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender",
        "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
        "PySide6.QtHttpServer",
    ],
    noarchive=False,
)

# -- bundle-filter-begin (tested by tests/test_build_spec.py) --
# Qt frameworks the app never loads, though PyInstaller's PySide6 hook
# collects them. Verified with otool: none of QtCore/QtGui/QtWidgets/
# QtNetwork/QtSvg (the only Qt modules imported) links any of these.
# QtDBus stays: QtGui links it. QtSvg stays: flags and the checkbox glyph.
_UNUSED_QT_FRAMEWORKS = (
    "QtOpenGL", "QtPdf", "QtQml", "QtQmlMeta", "QtQmlModels",
    "QtQmlWorkerScript", "QtQuick", "QtVirtualKeyboard", "QtVirtualKeyboardQml",
)
_UNUSED_QT_FRAMEWORK_DIRS = frozenset(f"{fw}.framework" for fw in _UNUSED_QT_FRAMEWORKS)


def _is_unused_qt_entry(dest: str, src: str) -> bool:
    """True when a collected file belongs to a Qt piece the app never loads.

    Matches every spelling the TOC uses for a removed framework, because each
    one left behind breaks `codesign` on the .app a different way: files
    inside `PySide6/Qt/lib/<Name>.framework/…`, the top-level `<Name>`
    SYMLINK entries the Qt hooks collect (BUNDLE turns those into
    `Contents/Frameworks/<Name>` and `Contents/Resources/<Name>` links
    pointing at a framework that is no longer there), and the same two
    spellings under `Contents/…` should they ever appear. Segments are
    compared whole, so e.g. `QtQuickWidgets` would never match `QtQuick`.
    """
    for path in (dest.replace("\\", "/"), src.replace("\\", "/")):
        for part in path.split("/"):
            if part in _UNUSED_QT_FRAMEWORKS or part in _UNUSED_QT_FRAMEWORK_DIRS:
                return True
    if "PySide6/Qt/translations/" in dest.replace("\\", "/"):
        # Qt's own .qm files: nothing installs a QTranslator (the app
        # translates with its own dict), so these never load.
        return True
    if dest.replace("\\", "/").endswith("/plugins/imageformats/libqpdf.dylib"):
        # Needs the dropped QtPdf to load at all.
        return True
    return False
# -- bundle-filter-end --


a.binaries = [e for e in a.binaries if not _is_unused_qt_entry(e[0], e[1])]
a.datas = [e for e in a.datas if not _is_unused_qt_entry(e[0], e[1])]

# A security product can inject its own msvcp140.dll into the process, so ship ours.
if IS_WIN:
    _system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    for _name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
                  "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll"):
        _path = _system32 / _name
        if _path.is_file() and not any(
                e[0].lower() == _name.lower() for e in a.binaries):
            a.binaries.append((_name, str(_path), "BINARY"))

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
    if IS_MAC:
        # macOS needs an .app, not a bare Unix executable: a downloaded raw
        # binary loses its +x bit, so Finder shows it as a document with a
        # question mark and a double-click does nothing. Built from the
        # one-dir tree for the same reason the Windows installer is -- the
        # one-file build re-extracts ~170 MB to /tmp on every launch.
        icns = ROOT / "assets" / "icon.icns"
        app = BUNDLE(
            coll,
            name="sushTun.app",
            icon=str(icns) if icns.exists() else None,
            bundle_identifier="com.soroushdeimi.sushtun",
            version=VERSION,
            info_plist={
                "CFBundleName": "sushTun",
                "CFBundleDisplayName": "sushTun",
                "CFBundleShortVersionString": VERSION,
                "CFBundleVersion": VERSION,
                # Qt 6 needs 12; saying so keeps older Macs from launching a
                # build that would only crash on a missing symbol.
                "LSMinimumSystemVersion": "12.0",
                "NSHighResolutionCapable": True,
                "LSApplicationCategoryType": "public.app-category.utilities",
            },
        )
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
