"""Guards for the sidebar window's scoped styles and the RTL popup text."""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui.ui.mac import PopupButton  # noqa: E402
from xrayui.ui.sidebar import Sidebar  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_sidebar_stylesheet_is_scoped(qapp):
    sb = Sidebar()
    assert sb.styleSheet().lstrip().startswith("QFrame#Sidebar{")


def test_toolbar_stylesheet_is_scoped(qapp, tmp_path, monkeypatch):
    from xrayui import paths
    from xrayui.ui.main_window import MainWindow
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    win = MainWindow(elevated=False)
    try:
        assert win.toolbar.styleSheet().lstrip().startswith("QWidget#Toolbar{")
        assert win.toolbar.title.styleSheet().find("border") == -1
    finally:
        win.close()


def test_popup_text_positions_ltr_label_first_from_the_left():
    label_x, value_x = PopupButton._text_positions(200, 60, 40, rtl=False)
    assert label_x == 10
    assert value_x == 70


def test_popup_text_positions_rtl_label_first_from_the_right():
    label_x, value_x = PopupButton._text_positions(200, 60, 40, rtl=True)
    # label ends at the right padding, value sits to its left
    assert label_x + 60 == 190
    assert value_x + 40 == label_x
