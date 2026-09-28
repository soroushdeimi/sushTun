"""Enter must press Save in every editing dialog, even after show."""
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

from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.core.subscription import Subscription  # noqa: E402
from xrayui.ui.dialogs import (  # noqa: E402
    ProfileEditDialog,
    SettingsDialog,  # noqa: E402
    SubscriptionEditDialog,
)
from xrayui.ui.dns_dialog import DnsDialog  # noqa: E402
from xrayui.ui.rule_editor import RuleEditorDialog, default_rule  # noqa: E402


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


@pytest.mark.parametrize("make", [
    lambda: ProfileEditDialog(Profile(name="de", protocol="vless", address="de.example.com",
                                      port=443, id="b1c2d3e4-0000-4000-8000-000000000001")),
    lambda: SubscriptionEditDialog(Subscription(name="Main", url="https://example.com/s")),
    lambda: RuleEditorDialog(default_rule()),
], ids=["profile", "subscription", "rule"])
def test_only_save_can_become_the_default(qapp, make):
    # On macOS an autoDefault Cancel took the default role once the dialog was
    # shown, so Enter in a field discarded the edit. Offscreen Qt does not
    # reassign it, so pin the cause: nothing but Save may be autoDefault.
    dlg = make()
    try:
        save = [b for b in dlg.findChildren(QPushButton) if b.isDefault()]
        assert len(save) == 1
        others = [b for b in dlg.findChildren(QPushButton) if b is not save[0]]
        assert others
        assert not any(b.autoDefault() for b in others)
        assert _defaults_after_show(qapp, dlg) == save
    finally:
        dlg.close()
