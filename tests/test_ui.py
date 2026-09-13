"""UI smoke tests: the dialogs and the main window actually construct and round-trip.

Skipped when PySide6 is missing so a contributor without it still gets a green
suite -- except under CI, where a skip must fail instead. A silent skip reads
exactly like a pass in the run summary, and that is how the UI came to be the
one part of the app no test ever executed.
"""
from __future__ import annotations

import copy
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

if os.environ.get("CI"):
    # A skip here looks identical to a pass in the run summary, which is how
    # the UI went untested in the first place. In CI a missing or broken
    # PySide6 must fail loudly instead.
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

# Must be set before the first QApplication; there is no display on a CI runner.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import dns as dns_mod  # noqa: E402
from xrayui.core import network as network_mod  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.core import speedtest as speedtest_mod  # noqa: E402
from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.ui import dialogs as dialogs_mod  # noqa: E402
from xrayui.ui.dialogs import ProfileEditDialog, SettingsDialog  # noqa: E402
from xrayui.ui.dns_dialog import DnsDialog  # noqa: E402
from xrayui.ui.server_table import COL_DELAY  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def defaults():
    return copy.deepcopy(app_settings.DEFAULTS)


@pytest.fixture
def warnings(monkeypatch):
    """Capture QMessageBox.warning text instead of blocking on a modal."""
    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: seen.append(a[2])), raising=False)
    return seen


# -- DNS dialog ------------------------------------------------------------
def test_dns_dialog_empty_round_trip_keeps_the_inherit_contract(qapp, defaults):
    out = DnsDialog(defaults["dns"]).result_dns()
    assert out["servers"] == []
    assert out["hosts"] == []
    assert out["query_strategy"] == ""
    # Empty must mean "inherit the template", never an empty server list.
    assert dns_mod.build_dns(out) == {}


def test_dns_dialog_preset_fills_and_round_trips(qapp, defaults, warnings):
    dlg = DnsDialog(defaults["dns"])
    dlg._fill(dns_mod.PRESETS["Quad9"])
    dlg.strategy.setCurrentIndex(dlg.strategy.findData("UseIPv4"))
    dlg.hosts.setPlainText("a.com = 1.2.3.4")
    dlg._save()

    assert not warnings
    out = dlg.result_dns()
    assert out["servers"] == dns_mod.PRESETS["Quad9"]
    assert out["query_strategy"] == "UseIPv4"
    # And the saved shape survives into the rendered Xray config.
    built = dns_mod.build_dns(out)
    assert built["servers"] == dns_mod.PRESETS["Quad9"]
    assert built["hosts"] == {"a.com": "1.2.3.4"}


def test_dns_dialog_reloads_what_it_saved(qapp, defaults):
    first = DnsDialog(defaults["dns"])
    first._fill(["1.1.1.1"])
    first.hosts.setPlainText("a.com = 1.2.3.4")
    first._save()
    saved = first.result_dns()

    second = DnsDialog(saved)
    assert second.servers.toPlainText().splitlines() == ["1.1.1.1"]
    assert second.hosts.toPlainText().splitlines() == ["a.com = 1.2.3.4"]


@pytest.mark.parametrize("entry,fragment", [
    ("8.8.8.8:5353", "scheme"),   # Xray parses a scheme-less entry as a URL
    ("localhost", "loop"),        # resolves back into this app's own resolver
    ("not a server", "spaces"),
    ("https://", "no server after the scheme"),
])
def test_dns_dialog_refuses_to_save_an_invalid_server(qapp, defaults, warnings, entry, fragment):
    dlg = DnsDialog(defaults["dns"])
    dlg.servers.setPlainText(entry)
    dlg._save()
    assert warnings, f"no warning for {entry}"
    assert fragment in warnings[-1]
    assert dlg.result() == 0, f"dialog accepted {entry}"


def test_dns_dialog_accepts_a_valid_server(qapp, defaults, warnings):
    dlg = DnsDialog(defaults["dns"])
    dlg.servers.setPlainText("https://1.1.1.1/dns-query")
    dlg._save()
    assert not warnings
    assert dlg.result() == 1


# -- Settings dialog -------------------------------------------------------
def test_settings_dialog_round_trips_the_new_knobs(qapp, defaults):
    dlg = SettingsDialog(defaults)
    assert dlg.values()["tun_mtu"] == 1420
    assert dlg.values()["log_level"] == "warning"

    dlg.tun_mtu.setValue(1280)
    dlg.log_level.setCurrentText("debug")
    values = dlg.values()
    assert values["tun_mtu"] == 1280
    assert values["log_level"] == "debug"
    assert values["ping_target"] == "1.1.1.1"


def test_geo_update_now_success_sets_last_update_and_status(qapp, defaults, tmp_path,
                                                              monkeypatch):
    monkeypatch.setattr(dialogs_mod.app_settings.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(dialogs_mod.geo_mod, "update", lambda source, fetch=None: None)
    dlg = SettingsDialog(defaults)
    assert dlg.geo_status.text() == "Never updated"

    dlg._update_geo_now()
    _pump(lambda: not dlg._geo_busy)

    assert dlg.geo_updated()
    assert dlg.geo_status.text() != "Never updated"
    assert dlg.values()["geo"]["last_update"] > 0


def test_geo_update_now_failure_shows_inline_no_popup(qapp, defaults, tmp_path, monkeypatch):
    monkeypatch.setattr(dialogs_mod.app_settings.paths, "base_dir", lambda: tmp_path)

    def fake_update(source, fetch=None):
        raise dialogs_mod.geo_mod.GeoUpdateError("new geo data rejected: bad category")

    monkeypatch.setattr(dialogs_mod.geo_mod, "update", fake_update)
    popups = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: popups.append(a) or None), raising=False)

    dlg = SettingsDialog(defaults)
    dlg._update_geo_now()
    _pump(lambda: not dlg._geo_busy)

    assert not dlg.geo_updated()
    assert "bad category" in dlg.geo_status.text()
    assert popups == []


def test_settings_dialog_offers_every_known_log_level(qapp, defaults):
    dlg = SettingsDialog(defaults)
    shown = [dlg.log_level.itemText(i) for i in range(dlg.log_level.count())]
    assert shown == list(app_settings.LOG_LEVELS)


# -- Profile edit dialog -----------------------------------------------------
def test_profile_edit_dialog_round_trips_alpn_and_spiderx(qapp):
    p = Profile(name="r", address="a.com", port=443, id="u", network="ws",
                security="reality", pbk="PUB", sid="ab", sni="www.test.com")
    dlg = ProfileEditDialog(p)
    assert dlg.f_alpn.text() == ""
    assert dlg.f_spx.text() == ""
    dlg.f_alpn.setText("h2,http/1.1")
    dlg.f_spx.setText("/spider")
    dlg._save()
    saved = dlg.result_profile()
    assert saved.alpn == "h2,http/1.1"
    assert saved.spx == "/spider"


# -- Main window -----------------------------------------------------------
@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    win = MainWindow(elevated=False)
    yield win
    win.close()


def test_main_window_exposes_the_dns_and_baseline_entry_points(window):
    assert window.btn_dns.text().startswith("DNS")
    assert "Baseline" in [b.text() for b in window.tools._buttons]


def test_tool_signals_reach_their_handlers(window):
    fired = []
    window._run_tool = lambda fn: fired.append(fn.__name__)
    window.tools.baselineRequested.emit()
    window.tools.throughputRequested.emit()
    assert fired == ["_baseline_fn", "_throughput_fn"]


def test_baseline_reports_plainly_when_not_connected(window):
    assert "Not connected" in window._baseline_fn()


def test_window_and_tray_are_branded_sushtun(window):
    assert window.windowTitle() == "sushTun"
    if window.tray is not None:
        assert window.tray.toolTip() == "sushTun"


# -- Window chrome ---------------------------------------------------------
class _FakeTray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *args):
        self.messages.append(args[1])


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS keeps its native title bar")
def test_title_bar_has_the_three_traffic_lights(window):
    kinds = [light.kind for light in window.titlebar.lights.lights]
    assert kinds == ["close", "minimize", "zoom"]
    assert window.titlebar.title.text() == window.windowTitle()


def test_close_hides_to_the_tray_and_keeps_the_tunnel_running(window):
    window.tray = _FakeTray()
    try:
        window.show()
        window.close()
        assert not window.isVisible()
        assert window.timer.isActive(), "closing the window must not stop the app"
        window.close()
        assert len(window.tray.messages) == 1, "the tray hint should show only once"
    finally:
        window.tray = None


def test_close_without_a_tray_shuts_the_window_down(window):
    window.tray = None
    window.show()
    window.close()
    assert not window.timer.isActive()


def test_quit_closes_even_with_a_tray(window, monkeypatch):
    window.tray = _FakeTray()
    monkeypatch.setattr(QApplication, "quit", lambda *a: None)
    window.show()
    window._quit()
    window.close()
    assert not window.timer.isActive()
    assert not window.tray.messages
    window.tray = None


# -- Server table integration ------------------------------------------------
def test_paste_import_adds_a_profile_from_clipboard(window):
    link = ("vless://11111111-1111-1111-1111-111111111111@1.2.3.4:443"
            "?encryption=none&type=tcp&security=none#Pasted")
    QApplication.clipboard().setText(link)
    window._paste_import()
    assert "Pasted" in [p.name for p in window.store.list()]
    assert "Imported 1 server" in window.step_label.text()


def test_paste_import_is_quiet_about_unusable_clipboard_content(window):
    QApplication.clipboard().setText("just some notes, not a server link")
    window.step_label.setText("")
    window._paste_import()
    assert window.store.list() == []
    assert window.step_label.text() != ""  # a quiet message, not a popup


def test_remove_duplicates_keeps_the_active_profile(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    window.store.save(Profile(name="A", address="x", port=1, id="u"))
    dup = window.store.save(Profile(name="A dup", address="x", port=1, id="u"))
    window.store.set_active(dup.uid)
    window._reload_profiles()

    window._remove_duplicates()

    remaining = window.store.list()
    assert len(remaining) == 1
    assert remaining[0].uid == dup.uid
    assert window.store.active_uid() == dup.uid


def _pump(condition, timeout=5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def test_test_button_toggles_to_cancel_while_a_test_runs(window, monkeypatch):
    profile = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window.store.set_active(profile.uid)
    window._reload_profiles()

    started = threading.Event()
    release = threading.Event()

    def fake_real_delay_all(profiles, on_result, cancel, **kwargs):
        started.set()
        release.wait(timeout=5)
        for p in profiles:
            on_result(p.uid, 10.0, None)

    monkeypatch.setattr(speedtest_mod, "real_delay_all", fake_real_delay_all)
    monkeypatch.setattr(network_mod, "detect_interface", lambda: SimpleNamespace(alias="eth0"))

    window._start_test([profile.uid], True)
    assert window.profiles.btn_test.text() == "Cancel"

    assert started.wait(timeout=5)
    release.set()
    _pump(lambda: window._test_cancel is None)

    assert window.profiles.btn_test.text() == "Test"
    assert window.results.get(profile.uid) == {"delay_ms": 10.0, "error": None, "skipped": False}


def test_test_result_from_a_background_thread_updates_the_right_row(window):
    profile = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window.store.set_active(profile.uid)
    window._reload_profiles()

    threading.Thread(
        target=lambda: window.testResultReceived.emit(profile.uid, 77.0, None)
    ).start()

    _pump(lambda: window.results.get(profile.uid) is not None)

    assert window.results.get(profile.uid) == {"delay_ms": 77.0, "error": None, "skipped": False}
    row = window.profiles.model.row_of_uid(profile.uid)
    idx = window.profiles.model.index(row, COL_DELAY)
    assert window.profiles.model.data(idx) == "77 ms"


# -- Routing combo / Reconnect now / tray submenu (Phase 2c) -----------------
def test_routing_combo_lists_sets_and_writes_mode(window):
    window.settings["routing"]["sets"] = [{"id": "s1", "name": "MySet", "rules": []}]
    window._refresh_routing_combo()
    assert [window.routing_combo.itemText(i) for i in range(window.routing_combo.count())] \
        == ["Simple", "MySet"]

    window.routing_combo.setCurrentIndex(window.routing_combo.findData("s1"))
    assert window.settings["routing"]["mode"] == "s1"


def test_reconnect_now_hidden_when_disconnected(window):
    # isVisible() reflects the whole ancestor chain, which is never shown
    # in an offscreen test; isHidden() reflects our own explicit
    # setVisible() call regardless of whether the window itself is shown.
    assert not window.conn.is_connected()
    window._needs_reconnect("Test change")
    assert window.btn_reconnect.isHidden()


def test_reconnect_now_appears_after_a_change_while_connected(window, monkeypatch):
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    window._needs_reconnect("Test change")
    assert not window.btn_reconnect.isHidden()
    assert window.step_label.text() == "Test change — reconnect to apply."


def test_reconnect_now_disconnects_then_connects_then_hides(window, monkeypatch):
    profile = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window.store.set_active(profile.uid)
    window._reload_profiles()

    calls = []
    monkeypatch.setattr(window.conn, "disconnect", lambda: calls.append("disconnect"))
    monkeypatch.setattr(window.conn, "connect", lambda p: calls.append(("connect", p.uid)))
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)

    window.btn_reconnect.setVisible(True)
    window._reconnect_now()
    _pump(lambda: not window._busy)

    assert calls == ["disconnect", ("connect", profile.uid)]
    assert window.btn_reconnect.isHidden()


def test_tray_routing_submenu_checks_current_mode_and_switching_updates_combo(window):
    from PySide6.QtWidgets import QMenu
    window.routing_menu = QMenu()
    window.settings["routing"]["sets"] = [{"id": "s1", "name": "MySet", "rules": []}]
    window._refresh_routing_combo()

    actions = window.routing_menu.actions()
    assert [a.text() for a in actions] == ["Simple", "MySet"]
    assert actions[0].isChecked()
    assert not actions[1].isChecked()

    actions[1].trigger()

    assert window.settings["routing"]["mode"] == "s1"
    assert window.routing_combo.currentData() == "s1"
    assert window.routing_menu.actions()[1].isChecked()
