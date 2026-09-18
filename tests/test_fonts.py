"""The Persian faces ship with the app and actually register with Qt."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.ui.app import _BUNDLED_FONTS, load_bundled_fonts  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_every_bundled_face_is_present():
    for name in _BUNDLED_FONTS:
        assert paths.font_file(name).exists(), name


def test_loading_registers_the_vazirmatn_family(qapp):
    families = load_bundled_fonts()
    assert any(f.startswith("Vazirmatn") for f in families), families
