"""Settings → Port forwarding: one row per forward, checked before Done."""
from __future__ import annotations

import copy
import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QAbstractButton, QApplication  # noqa: E402

from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.ui.settings_window import SettingsWindow  # noqa: E402

SSH = {"port": 2222, "target": "10.8.0.5:22", "via": "proxy", "network": "tcp"}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def defaults():
    return copy.deepcopy(app_settings.DEFAULTS)


def _page(settings):
    win = SettingsWindow(settings)
    return win, win._pages["forwards"]


def test_empty_by_default(qapp, defaults):
    win, page = _page(defaults)
    assert page.collect() == [] and page.problem() is None
    assert win.values()["forwards"] == []


def test_saved_forwards_come_back_as_rows(qapp, defaults):
    defaults["forwards"] = [SSH, {"port": 5353, "target": "dns.example:53",
                                  "via": "direct", "network": "tcp,udp"}]
    win, page = _page(defaults)
    assert page.collect() == defaults["forwards"]
    assert win.values()["forwards"] == defaults["forwards"]


def test_add_and_remove_a_row(qapp, defaults):
    _win, page = _page(defaults)
    page.btn_add.click()
    row, port, target, via, network = page._rows[0]
    port.setValue(8443)
    target.setText(" nas.example:443 ")
    via.setCurrentIndex(via.findData("direct"))
    network.setCurrentIndex(network.findData("tcp,udp"))
    assert page.collect() == [{"port": 8443, "target": "nas.example:443",
                               "via": "direct", "network": "tcp,udp"}]
    row.findChild(QAbstractButton).click()
    assert page.collect() == []


@pytest.mark.parametrize("forwards,reason", [
    ([{**SSH, "target": "no-port"}], "is not host:port"),
    ([{**SSH, "port": 10808}], "already used by sushTun"),    # the local SOCKS port
    ([SSH, {**SSH, "target": "other.example:22"}], "already used by sushTun"),
])
def test_bad_rows_block_done(qapp, defaults, forwards, reason):
    defaults["forwards"] = forwards
    win, page = _page(defaults)
    assert reason in page.problem()
    win._on_done()
    assert not win._busy
    assert reason in win._status_label.text()


def test_a_forward_may_not_take_the_multi_exit_port(qapp, defaults):
    defaults["exits"].update(enabled=True, port=2222, password="pw123456",
                             items=[{"user": "de", "profile_uid": "gone"}])
    defaults["forwards"] = [SSH]
    _win, page = _page(defaults)
    assert "already used by sushTun" in page.problem({"enabled": True, "port": 2222})
    assert page.problem({"enabled": False, "port": 2222}) is None
