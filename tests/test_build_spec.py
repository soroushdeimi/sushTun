"""The packaged build must carry every non-Python file the UI loads by path."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_build_spec_bundles_every_ui_data_file():
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    ui = ROOT / "xrayui" / "ui"
    suffixes = {p.suffix for p in ui.iterdir() if p.is_file() and p.suffix not in {".py", ".pyc"}}
    assert suffixes, "expected at least the checkbox glyph (.svg)"
    for suffix in suffixes:
        # A glob per suffix; a new data file type needs its own line in the spec.
        assert f'glob("*{suffix}")' in spec, f"build.spec does not bundle xrayui/ui/*{suffix}"


def test_build_spec_bundles_the_country_flags():
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    assert 'ROOT / "assets" / "flags"' in spec
    assert '"*.svg"' in spec
    assert '"*.json"' in spec
    assert '"assets/flags"' in spec
    assert (ROOT / "assets" / "flags" / "names.json").is_file()


def test_build_spec_drops_unused_qt_but_keeps_what_the_app_loads():
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    for framework in ("QtQml", "QtQuick", "QtPdf", "QtVirtualKeyboard", "QtOpenGL"):
        assert f'"{framework}"' in spec, f"{framework} is no longer excluded from the build"
    start = spec.index("_UNUSED_QT_FRAMEWORKS")
    unused = spec[start:spec.index(")", start)]
    for framework in ("QtSvg", "QtDBus", "QtCore", "QtGui", "QtWidgets", "QtNetwork"):
        # QtSvg renders the flags and the checkbox glyph, QtDBus is linked by
        # QtGui: excluding either would break the packaged app at runtime.
        assert framework not in unused, f"{framework} must stay in the build"
    assert '"PySide6.QtSvg"' not in spec
    assert '"PySide6.QtDBus"' not in spec
    # Qt's own .qm translations (nothing installs a QTranslator) and the
    # QtPdf-bound image plugin go through the same collected-files filter.
    assert "Qt/translations" in spec
    assert "libqpdf" in spec


def test_build_spec_ships_the_msvc_runtime_dlls():
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
                 "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll"):
        assert f'"{name}"' in spec, f"build.spec does not ship {name}"
    assert '"BINARY"' in spec
    # The DLLs must be added after the Qt filter, when the binaries are final,
    # and only on Windows.
    filter_line = spec.index("a.datas = [e for e in a.datas if not _is_unused_qt_entry")
    # The DLLs must be added after the Qt filter, when the binaries are final,
    # and only on Windows.
    dlls = spec.index('"msvcp140.dll"')
    assert filter_line < dlls
    assert spec.index("if IS_WIN:", filter_line) < dlls


def test_release_yml_verifies_the_msvc_runtime_dlls():
    yml = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    job = yml[yml.index("windows-installer:"):]
    job = job[:job.index("macos-app:")]
    assert "Verify MSVC runtime DLLs" in job
    assert "msvcp140.dll" in job
    assert "exit 1" in job


def _filter_from_spec():
    """The spec's own filter function, exec'd from its marked block so this
    test exercises the real matcher, not a copy of it."""
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    start = spec.index("# -- bundle-filter-begin")
    end = spec.index("# -- bundle-filter-end --")
    namespace: dict = {}
    exec(compile(spec[start:end], "build.spec", "exec"), namespace)
    return namespace["_is_unused_qt_entry"]


def test_build_spec_filter_drops_every_spelling_of_removed_frameworks():
    # A removed framework must vanish in every TOC spelling, or the .app is
    # left with symlinks to nowhere and `codesign` fails: files inside the
    # framework dir, the top-level SYMLINK entries the Qt hooks collect
    # (BUNDLE turns those into Contents/Frameworks/<Name> and
    # Contents/Resources/<Name>), and the Contents/… spellings themselves.
    drop = _filter_from_spec()
    removed = [
        ("PySide6/Qt/lib/QtQml.framework/Versions/A/QtQml",
         "/venv/PySide6/Qt/lib/QtQml.framework/Versions/A/QtQml"),
        ("PySide6/Qt/lib/QtPdf.framework/QtPdf", "Versions/Current/QtPdf"),
        ("PySide6/Qt/lib/QtQuick.framework/Versions/Current", "A"),
        ("QtQml", "PySide6/Qt/lib/QtQml.framework/Versions/A/QtQml"),
        ("QtPdf", "PySide6/Qt/lib/QtPdf.framework/Versions/A/QtPdf"),
        ("QtQuick", "PySide6/Qt/lib/QtQuick.framework/Versions/A/QtQuick"),
        ("QtVirtualKeyboardQml", "PySide6/Qt/lib/QtVirtualKeyboardQml.framework/Versions/A/x"),
        ("Contents/Frameworks/QtQml", "Contents/Frameworks/QtQml"),
        ("Contents/Resources/QtQml", "Contents/Resources/QtQml"),
        ("Contents/Frameworks/QtPdf", "Contents/Frameworks/QtPdf"),
        ("PySide6/Qt/translations/qt_fa.qm", "/venv/PySide6/Qt/translations/qt_fa.qm"),
        ("PySide6/Qt/plugins/imageformats/libqpdf.dylib", "/venv/.../libqpdf.dylib"),
    ]
    for dest, src in removed:
        assert drop(dest, src), f"filter keeps {(dest, src)}"
    kept = [
        ("PySide6/Qt/lib/QtSvg.framework/Versions/A/QtSvg", "/venv/.../QtSvg"),
        ("PySide6/Qt/lib/QtDBus.framework/Versions/A/QtDBus", "/venv/.../QtDBus"),
        ("PySide6/Qt/lib/QtWidgets.framework/Versions/A/QtWidgets", "/venv/.../QtWidgets"),
        ("QtSvg", "/venv/PySide6/QtSvg.abi3.so"),
        ("PySide6/Qt/plugins/imageformats/libqsvg.dylib", "/venv/.../libqsvg.dylib"),
        ("PySide6/Qt/plugins/platforms/libqcocoa.dylib", "/venv/.../libqcocoa.dylib"),
    ]
    for dest, src in kept:
        assert not drop(dest, src), f"filter drops {(dest, src)}"
