"""Exit-country flags in the server table, the header and the main window."""
from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import geo_exit  # noqa: E402
from xrayui.core import network as network_mod  # noqa: E402
from xrayui.core import speedtest as speedtest_mod  # noqa: E402
from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.i18n import set_language  # noqa: E402
from xrayui.ui import flags  # noqa: E402
from xrayui.ui.connection_header import ConnectionHeader  # noqa: E402
from xrayui.ui.server_table import COL_DELAY, COL_NAME, ProfileTableModel  # noqa: E402
from xrayui.ui.settings_window import SettingsWindow  # noqa: E402

A = Profile(name="Berlin", protocol="vless", address="a.example.com", port=443, id="u", uid="a")
B = Profile(name="Unknown", protocol="vless", address="b.example.com", port=443, id="u", uid="b")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


def _model(**results) -> ProfileTableModel:
    m = ProfileTableModel()
    m.set_profiles([A, B], None)
    m.set_results(results)
    return m


def _name_cell(m, row, role):
    return m.data(m.index(row, COL_NAME), role)


def test_name_cell_has_a_flag_only_when_the_exit_is_known(qapp):
    m = _model(a={"delay_ms": 50, "error": None, "country": "de", "exit_ip": "152.233.20.199"})
    icon = _name_cell(m, 0, Qt.DecorationRole)
    assert icon is not None and not icon.isNull()
    assert _name_cell(m, 1, Qt.DecorationRole) is None


def test_name_tooltip_says_where_the_server_exits(qapp):
    m = _model(a={"delay_ms": 50, "error": None, "country": "de", "exit_ip": "152.233.20.199"})
    assert _name_cell(m, 0, Qt.ToolTipRole) == "Exits in Germany · 152.233.20.199"
    assert _name_cell(m, 1, Qt.ToolTipRole) == "Press Test to find out where this server exits"


def test_name_tooltip_uses_the_persian_country_name_in_fa(qapp):
    set_language("fa")
    m = _model(a={"delay_ms": 50, "error": None, "country": "de", "exit_ip": "1.2.3.4"})
    tip = _name_cell(m, 0, Qt.ToolTipRole)
    assert "آلمان" in tip and "1.2.3.4" in tip


def test_a_new_measurement_keeps_the_known_exit(qapp):
    m = _model(a={"delay_ms": 50, "error": None, "country": "de", "exit_ip": "1.2.3.4"})
    m.update_result("a", None, "timeout")
    assert m.country_of("a") == "de"
    m.update_detail("a", {"cold_ms": 90.0})
    assert m.country_of("a") == "de"


def test_delay_tooltip_shows_the_first_connection_time_only_when_known(qapp):
    m = _model(a={"delay_ms": 196.0, "error": None, "cold_ms": 766.0},
               b={"delay_ms": 196.0, "error": None, "cold_ms": None})
    tip = m.data(m.index(0, COL_DELAY), Qt.ToolTipRole)
    assert "First connection" in tip and "766 ms" in tip
    assert m.data(m.index(1, COL_DELAY), Qt.ToolTipRole) is None


def test_flag_pixmaps_are_cached_and_hidpi_ready(qapp):
    one = flags.flag_pixmap("de")
    assert one is flags.flag_pixmap("de")
    assert one.width() == round(flags.FLAG_W * one.devicePixelRatio())
    assert flags.flag_pixmap("xx") is None and flags.flag_pixmap(None) is None
    assert flags.flag_pixmap("de", 16, 12) is not one


def test_header_shows_flag_and_country_name_in_the_meta_line(qapp):
    h = ConnectionHeader()
    h.set("endpoint", "a.example.com:443")
    h.set_exit("de")
    assert h._meta_full.startswith("Germany")
    assert "a.example.com:443" in h._meta_full
    assert not h._flag.isHidden() and h._flag.pixmap() is not None

    h.set_exit(None)
    assert h._flag.isHidden()
    assert "Germany" not in h._meta_full


# -- settings ----------------------------------------------------------------
def test_delay_test_combo_round_trips(qapp):
    import copy

    from xrayui.core import settings as app_settings

    cfg = copy.deepcopy(app_settings.DEFAULTS)
    win = SettingsWindow(cfg)
    combo = win._pages["general"].delay_mode
    assert combo.currentData() == "warm"
    assert win.values()["speedtest"]["mode"] == "warm"
    assert win.values()["speedtest"]["url"] == cfg["speedtest"]["url"]

    combo.setCurrentIndex(combo.findData("cold"))
    assert win.values()["speedtest"]["mode"] == "cold"

    cfg["speedtest"]["mode"] = "cold"
    assert SettingsWindow(cfg)._pages["general"].delay_mode.currentData() == "cold"


# -- main window -------------------------------------------------------------
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


def _pump(condition, timeout=5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def test_a_test_run_stores_the_exit_and_a_failed_detection_keeps_it(window, monkeypatch):
    p = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window._reload_profiles()
    seen = {}

    def fake_real_delay_all(profiles, on_result, cancel, **kw):
        seen.update(kw)
        for pr in profiles:
            on_result(pr.uid, 10.0, None)
            kw["on_detail"](pr.uid, window_details.pop(0))

    window_details = [
        {"cold_ms": 40.0, "country": "de", "exit_ip": "1.2.3.4"},
        {"cold_ms": 50.0},
    ]
    monkeypatch.setattr(speedtest_mod, "real_delay_all", fake_real_delay_all)
    monkeypatch.setattr(network_mod, "detect_interface", lambda: SimpleNamespace(alias="eth0"))

    for _ in range(2):
        window._start_test([p.uid], True)
        _pump(lambda: window._test_cancel is None)
        QApplication.processEvents()

    assert seen["mode"] == "warm"
    stored = window.results.get(p.uid)
    assert stored["country"] == "de" and stored["exit_ip"] == "1.2.3.4"
    assert stored["cold_ms"] == 50.0
    assert window.profiles.model.country_of(p.uid) == "de"


def test_connecting_detects_the_exit_off_the_ui_thread(window, monkeypatch):
    p = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window.store.set_active(p.uid)
    window._reload_profiles()
    threads = []

    def fake_detect(proxy=None, timeout=8.0):
        threads.append((threading.current_thread() is threading.main_thread(), proxy))
        return geo_exit.ExitInfo("de", "9.9.9.9")

    monkeypatch.setattr(geo_exit, "detect", fake_detect)
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    monkeypatch.setattr(type(window.conn.state), "profile_uid", property(lambda _s: p.uid))

    window._on_conn_done()
    _pump(lambda: window.results.get(p.uid) is not None)

    assert threads == [(False, None)]
    assert window.results.get(p.uid) == {"country": "de", "exit_ip": "9.9.9.9"}
    assert window.profiles.model.country_of(p.uid) == "de"
    assert not window.toolbar.subtitle_flag.isHidden()


def test_a_failed_connect_does_not_probe(window, monkeypatch):
    monkeypatch.setattr(geo_exit, "detect",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no probe")))
    monkeypatch.setattr(window.conn, "is_connected", lambda: False)
    monkeypatch.setattr("xrayui.ui.main_window.QMessageBox.warning", lambda *a, **k: None)
    window._on_conn_done(error="boom")


def test_mode_is_passed_from_settings(window, monkeypatch):
    p = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window.settings["speedtest"]["mode"] = "cold"
    seen = {}
    monkeypatch.setattr(speedtest_mod, "real_delay_all",
                        lambda profiles, on_result, cancel, **kw: seen.update(kw))
    monkeypatch.setattr(network_mod, "detect_interface", lambda: SimpleNamespace(alias="eth0"))
    window._start_test([p.uid], True)
    _pump(lambda: window._test_cancel is None)
    assert seen["mode"] == "cold"


def test_flag_emoji_is_the_pair_of_regional_indicators(qapp):
    assert flags.flag_emoji("de") == "\U0001F1E9\U0001F1EA"
    assert flags.flag_emoji("JP") == "\U0001F1EF\U0001F1F5"
    assert flags.flag_emoji("zz") == ""      # not a country the app names
    assert flags.flag_emoji(None) == ""


def test_a_flag_pixmap_is_drawn_without_an_emoji_font_too(qapp, monkeypatch):
    monkeypatch.setattr(flags, "_emoji_family", lambda: "")
    assert flags._fit_emoji_font("\U0001F1E9\U0001F1EA", 20, 15) is None

    pix = flags.flag_pixmap("de")  # the Windows path: the bundled SVG
    assert pix is not None and not pix.isNull()


def test_the_emoji_path_draws_a_flag_when_the_system_has_one(qapp):
    if not flags._emoji_family():
        pytest.skip("this system has no colour emoji font")
    pix = flags.flag_pixmap("de", 20, 15)
    assert pix is not None and not pix.isNull()

