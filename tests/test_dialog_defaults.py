"""Enter must press Save in the DNS and Settings dialogs, even after show."""
from __future__ import annotations

import copy
import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.ui.dialogs import SettingsDialog  # noqa: E402
from xrayui.ui.dns_dialog import DnsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _defaults_after_show(qapp, dlg) -> list[QPushButton]:
    dlg.show()
    qapp.processEvents()
    return [b for b in dlg.findChildren(QPushButton) if b.isVisible() and b.isDefault()]


def test_dns_dialog_keeps_save_as_the_default(qapp):
    settings = copy.deepcopy(DEFAULTS)
    dlg = DnsDialog(settings["dns"], settings["routing"])
    try:
        assert _defaults_after_show(qapp, dlg) == [dlg.btn_save]
        others = [b for b in dlg.findChildren(QPushButton) if b is not dlg.btn_save]
        assert others
        assert not any(b.autoDefault() for b in others)
    finally:
        dlg.close()


def test_settings_dialog_keeps_save_as_the_default(qapp):
    dlg = SettingsDialog(copy.deepcopy(DEFAULTS))
    try:
        assert _defaults_after_show(qapp, dlg) == [dlg.btn_save]
        others = [b for b in dlg.findChildren(QPushButton) if b is not dlg.btn_save]
        assert others
        assert not any(b.autoDefault() for b in others)
    finally:
        dlg.close()
