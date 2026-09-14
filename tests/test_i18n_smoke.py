"""fa smoke test: the main window and every dialog build offscreen under
Persian without raising, the app is right-to-left, and the LTR-exempt
widgets (TitleBar, LogView, technical inputs) stay left-to-right.
"""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import i18n, paths  # noqa: E402
from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.core.subscription import Subscription  # noqa: E402
from xrayui.ui.dialogs import (  # noqa: E402
    ImportDialog,
    ProfileEditDialog,
    SettingsDialog,
    SubscriptionEditDialog,
)
from xrayui.ui.dns_dialog import DnsDialog  # noqa: E402
from xrayui.ui.routing_dialog import RoutingDialog  # noqa: E402
from xrayui.ui.rule_editor import RuleEditorDialog, default_rule  # noqa: E402
from xrayui.ui.server_table import QrDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fa(qapp):
    """language=fa and an RTL app, exactly as ui.app.run() sets up at
    startup -- reverted afterward so other test files still see en/LTR."""
    i18n.set_language("fa")
    qapp.setLayoutDirection(Qt.RightToLeft)
    yield
    i18n.set_language("en")
    qapp.setLayoutDirection(Qt.LeftToRight)


@pytest.fixture
def window(qapp, tmp_path, monkeypatch, fa):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    win = MainWindow(elevated=False)
    yield win
    win.close()


def test_app_is_right_to_left(fa, qapp):
    assert qapp.layoutDirection() == Qt.RightToLeft


def test_main_window_shows_persian_and_keeps_titlebar_and_log_ltr(window):
    assert window.btn_connect.text() == "اتصال"
    assert window.windowTitle() == "sushTun"  # the product name, never translated
    if window.titlebar is not None:
        assert window.titlebar.layoutDirection() == Qt.LeftToRight
    assert window.log.layoutDirection() == Qt.LeftToRight


def test_import_dialog_builds_in_persian(fa, qapp):
    dlg = ImportDialog()
    try:
        assert dlg.windowTitle() == "وارد کردن سرورها"
        assert dlg.link_edit.layoutDirection() == Qt.LeftToRight
        assert dlg.json_edit.layoutDirection() == Qt.LeftToRight
    finally:
        dlg.close()


@pytest.mark.parametrize("protocol", [
    "vless", "vmess", "trojan", "shadowsocks", "hysteria2", "wireguard",
])
def test_profile_edit_dialog_builds_in_persian_for_every_protocol(fa, qapp, protocol):
    p = Profile(name="p", protocol=protocol, address="a.example.com", port=443, id="u",
               pbk="pub" if protocol == "wireguard" else "")
    dlg = ProfileEditDialog(p)
    try:
        assert dlg.windowTitle() == "ویرایش سرور"
        assert dlg.f_address.layoutDirection() == Qt.LeftToRight
        assert dlg.f_id.layoutDirection() == Qt.LeftToRight
    finally:
        dlg.close()


def test_settings_dialog_builds_in_persian(fa, qapp):
    dlg = SettingsDialog(DEFAULTS)
    try:
        assert dlg.windowTitle() == "تنظیمات"
        assert dlg.ping_target.layoutDirection() == Qt.LeftToRight
        assert dlg.language.itemText(1) == "فارسی"
    finally:
        dlg.close()


def test_routing_dialog_and_rule_editor_build_in_persian(fa, qapp):
    dlg = RoutingDialog(DEFAULTS["routing"])
    try:
        assert dlg.windowTitle() == "دور زدن و مسیریابی"
        assert dlg.tabs.tabText(0) == "ساده"
        assert dlg.tabs.tabText(1) == "مجموعه قوانین"
        assert dlg.domains.layoutDirection() == Qt.LeftToRight
        assert dlg.ips.layoutDirection() == Qt.LeftToRight
        assert dlg.proxy.layoutDirection() == Qt.LeftToRight
    finally:
        dlg.close()

    rule_dlg = RuleEditorDialog(default_rule())
    try:
        assert rule_dlg.windowTitle() == "ویرایش قانون"
        assert rule_dlg.domains.layoutDirection() == Qt.LeftToRight
        assert rule_dlg.ips.layoutDirection() == Qt.LeftToRight
    finally:
        rule_dlg.close()


def test_dns_dialog_builds_in_persian(fa, qapp):
    dlg = DnsDialog(DEFAULTS["dns"], DEFAULTS["routing"])
    try:
        assert dlg.servers.layoutDirection() == Qt.LeftToRight
        assert dlg.hosts.layoutDirection() == Qt.LeftToRight
        assert dlg.domestic.layoutDirection() == Qt.LeftToRight
        assert dlg.raw_override.layoutDirection() == Qt.LeftToRight
    finally:
        dlg.close()


def test_subscription_edit_dialog_builds_in_persian(fa, qapp):
    dlg = SubscriptionEditDialog(Subscription())
    try:
        assert dlg.windowTitle() == "ویرایش اشتراک"
        assert dlg.f_url.layoutDirection() == Qt.LeftToRight
    finally:
        dlg.close()


def test_qr_dialog_builds_in_persian(fa, qapp):
    dlg = QrDialog("My server", "vless://uuid@example.com:443?type=tcp#name")
    try:
        assert "کد QR" in dlg.windowTitle()
    finally:
        dlg.close()
