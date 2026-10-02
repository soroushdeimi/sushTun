"""The Chains sidebar item has its own icon, drawn like the other sidebar glyphs."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui.ui import icons  # noqa: E402
from xrayui.ui.sidebar import Sidebar  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_chains_item_does_not_reuse_the_routing_icon(qapp):
    bar = Sidebar()
    assert bar.item_chains._icon_name == "chains"
    assert bar.item_routing._icon_name == "routing"
    assert icons._PATHS["chains"] != icons._PATHS["routing"]
    one = icons.icon("chains", "#ffffff").pixmap(16, 16).toImage()
    other = icons.icon("routing", "#ffffff").pixmap(16, 16).toImage()
    assert one != other
    bar.close()


@pytest.mark.parametrize("scale", [1, 1.25, 2])
def test_icons_have_an_exact_render_for_each_display_scale(qapp, scale):
    pixmap = icons.icon("chains", "#ffffff").pixmap(QSize(16, 16), scale)
    assert pixmap.width() == round(16 * scale)
    assert pixmap.devicePixelRatio() == scale
    assert any(pixmap.toImage().pixelColor(x, pixmap.height() // 2).alpha() > 0
               for x in range(pixmap.width()))
