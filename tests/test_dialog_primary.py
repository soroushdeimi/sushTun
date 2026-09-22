"""Dialogs show their main button in the primary colour; the profile form scrolls."""
from __future__ import annotations

import copy
import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea  # noqa: E402

from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.core.subscription import Subscription  # noqa: E402
from xrayui.ui import theme  # noqa: E402
from xrayui.ui.dialogs import (  # noqa: E402
    ImportDialog,
    ProfileEditDialog,
    SettingsDialog,
    SubscriptionEditDialog,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def themed(qapp, flush_widgets):
    old = qapp.styleSheet()
    flush_widgets()
    qapp.setStyleSheet(theme.STYLESHEET)
    yield qapp
    flush_widgets()
    qapp.setStyleSheet(old)


def _vless():
    return Profile(name="Germany 1", protocol="vless", address="de.example.com",
                   port=443, id="b1c2d3e4-0000-4000-8000-000000000001")


@pytest.mark.parametrize("make", [
    lambda: ImportDialog(),
    lambda: ProfileEditDialog(_vless()),
    lambda: SubscriptionEditDialog(Subscription(name="Main", url="https://example.com/s")),
    lambda: SettingsDialog(copy.deepcopy(DEFAULTS)),
], ids=["import", "profile", "subscription", "settings"])
def test_the_default_button_is_painted_as_primary(themed, make):
    dlg = make()
    try:
        dlg.show()
        themed.processEvents()
        primary = [b for b in dlg.findChildren(QPushButton) if b.objectName() == "Primary"]
        assert len(primary) == 1
        button = primary[0]
        assert button.isDefault()
        # Real pixels: a spot inside the button's padding is the accent blue.
        color = button.grab().toImage().pixelColor(12, button.height() // 2)
        assert color.blue() > 200 and color.red() < 60, color.name()
    finally:
        dlg.close()


def test_profile_form_scrolls_and_the_dialog_fits_a_small_screen(themed):
    dlg = ProfileEditDialog(_vless())
    try:
        assert isinstance(dlg.tabs.widget(0), QScrollArea)
        assert dlg.minimumSizeHint().height() <= 560
        dlg.show()
        themed.processEvents()
        assert dlg.height() <= 620
    finally:
        dlg.close()
