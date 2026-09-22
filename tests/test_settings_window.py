"""SettingsWindow tests: sidebar topics, staged edits, off-thread validation.

Mirrors the SettingsDialog coverage from test_ui.py so the new window keeps
exactly the same behaviour and API (values()/geo_updated()/restored()) --
leaving SettingsDialog itself untouched for now.

Skipped when PySide6 is missing so a contributor without it still gets a
green suite -- except under CI, where a skip must fail instead.
"""
from __future__ import annotations

import copy
import json
import os
import time

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

# Must be set before the first QApplication; there is no display on a CI runner.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QFileDialog,
    QLabel,
    QMessageBox,
)

from xrayui import paths  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.i18n import set_language, tr  # noqa: E402
from xrayui.ui import settings_window as sw_mod  # noqa: E402
from xrayui.ui.settings_window import SettingsWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def defaults():
    return copy.deepcopy(app_settings.DEFAULTS)


@pytest.fixture(autouse=True)
def _reset_language():
    """Each parametrised case flips the app language; leave it English."""
    yield
    set_language("en")


@pytest.fixture
def check_ok(monkeypatch):
    """Make Done's off-thread xray validation pass without an xray binary."""
    monkeypatch.setattr(sw_mod.xraycheck, "check_config", lambda *a, **k: None)


def _pump(condition, timeout=5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def _done_and_wait(win) -> None:
    win._on_done()
    _pump(lambda: not win._busy)


# -- Topics and layout -------------------------------------------------------
def test_sidebar_covers_every_topic_with_a_tooltip_and_accessible_name(qapp, defaults):
    win = SettingsWindow(defaults)
    assert [k for k, *_ in sw_mod.TOPICS] == list(win._pages)
    for item in win._sidebar_items:
        assert item.text()
        assert item.toolTip() == item.text()
        assert item.accessibleName() == item.text()
        assert item.isCheckable()


def test_selecting_a_topic_shows_its_page_and_highlights_its_tile(qapp, defaults):
    win = SettingsWindow(defaults)
    keys = list(win._pages)
    for key in keys:
        win._select_topic(key)
        assert win._stack.currentWidget().widget() is win._pages[key]
        selected = keys.index(key)
        for i, item in enumerate(win._sidebar_items):
            assert item.isChecked() is (i == selected)


def test_opens_on_the_requested_topic(qapp, defaults):
    win = SettingsWindow(defaults, topic="anti-filter")
    assert win._stack.currentWidget().widget() is win._pages["anti-filter"]


def test_done_is_the_default_button(qapp, defaults):
    win = SettingsWindow(defaults)
    assert win.btn_done.isDefault()
    assert win.btn_done.autoDefault()


def test_values_exposes_the_settings_dialog_schema(qapp, defaults):
    win = SettingsWindow(defaults)
    assert set(win.values()) == {
        "ping_target", "sample_seconds", "tun_mtu", "log_level",
        "language", "geo", "core", "startup", "updates", "exits", "gateway", "forwards",
    }


def _problems(widget, where: str) -> list[str]:
    problems: list[str] = []
    for w in widget.findChildren(QLabel) + widget.findChildren(QAbstractButton):
        if not w.isVisible() or not w.text().strip():
            continue
        hint = w.sizeHint().width()
        if w.width() >= hint:
            continue
        if isinstance(w, QLabel):
            if w.wordWrap():
                if w.height() >= w.heightForWidth(w.width()):
                    continue
                problems.append(
                    f"[{where}] QLabel {w.text()!r} {w.width()}x{w.height()} "
                    f"shorter than the {w.heightForWidth(w.width())}px it wraps to")
            elif w.toolTip():
                continue
            else:
                problems.append(
                    f"[{where}] QLabel {w.text()!r} {w.width()}px < sizeHint "
                    f"{hint}px and no tooltip")
        else:
            problems.append(
                f"[{where}] {type(w).__name__} {w.text()!r} {w.width()}px < sizeHint {hint}px")
    return problems


@pytest.mark.parametrize("lang", ("en", "fa"))
@pytest.mark.parametrize("width,height", [(820, 560), (1040, 700)])
@pytest.mark.parametrize("topic", ["general", "anti-filter", "local-proxy", "geo-data",
                                   "startup", "backup", "language"])
def test_settings_window_does_not_clip(qapp, defaults, width, height, topic, lang):
    set_language(lang)
    win = SettingsWindow(defaults, topic=topic)
    win.resize(width, height)
    win.show()
    qapp.processEvents()
    qapp.processEvents()
    try:
        problems = _problems(win, f"{lang} {width}x{height} {topic}")
    finally:
        win.close()
    assert not problems, "Clipped widgets:\n" + "\n".join(problems)


@pytest.mark.parametrize("width,height", [(820, 560), (1040, 700)])
def test_window_is_not_larger_than_requested(qapp, defaults, width, height):
    win = SettingsWindow(defaults)
    win.resize(width, height)
    win.show()
    qapp.processEvents()
    assert win.width() <= width
    assert win.height() <= height
    win.close()


def test_settings_window_builds_in_persian(qapp, defaults):
    set_language("fa")
    win = SettingsWindow(defaults)
    assert win.windowTitle() == tr("Settings")
    assert win._sidebar_items[0].text() == tr("General")
    assert win._sidebar_items[1].text() == tr("Anti-filter")
    assert win._sidebar_items[3].text() == tr("Geo data")


# -- Field round-trips -------------------------------------------------------
def test_settings_window_round_trips_the_new_knobs(qapp, defaults):
    win = SettingsWindow(defaults)
    assert win.values()["tun_mtu"] == 1420
    assert win.values()["log_level"] == "warning"

    win._pages["general"].tun_mtu.setValue(1280)
    win._pages["general"].log_level.setCurrentText("debug")
    values = win.values()
    assert values["tun_mtu"] == 1280
    assert values["log_level"] == "debug"
    assert values["ping_target"] == "1.1.1.1"


def test_settings_window_offers_every_known_log_level(qapp, defaults):
    win = SettingsWindow(defaults)
    shown = [win._pages["general"].log_level.itemText(i)
             for i in range(win._pages["general"].log_level.count())]
    assert shown == list(app_settings.LOG_LEVELS)


def test_settings_window_advanced_fields_persist(qapp, defaults, check_ok):
    win = SettingsWindow(defaults)
    win._pages["anti-filter"].frag_enabled.setChecked(True)
    win._pages["anti-filter"].frag_packets.setText("1-3")
    win._pages["anti-filter"].frag_length.setText("50-100")
    win._pages["anti-filter"].frag_interval.setText("5-10")
    win._pages["anti-filter"].frag_max_split.setValue(100)
    win._pages["anti-filter"].mux_enabled.setChecked(True)
    win._pages["anti-filter"].mux_concurrency.setValue(4)
    win._pages["anti-filter"].mux_xudp_concurrency.setValue(32)
    win._pages["anti-filter"].mux_xudp_udp443.setCurrentText("allow")
    win._pages["local-proxy"].sniff_enabled.setChecked(False)
    win._pages["local-proxy"].sniff_route_only.setChecked(True)
    win._pages["local-proxy"].socks_port.setValue(23456)
    win._pages["local-proxy"].allow_lan.setChecked(True)
    win._pages["local-proxy"].lan_user.setText("u1")
    win._pages["local-proxy"].lan_pass.setText("p1")
    win._pages["local-proxy"].default_fp.setCurrentIndex(
        win._pages["local-proxy"].default_fp.findData("chrome"))
    win._pages["startup"].start_minimized.setChecked(True)
    win._pages["startup"].auto_connect.setChecked(True)

    core = win.values()["core"]
    assert core["fragment"] == {"enabled": True, "packets": "1-3", "length": "50-100",
                                "interval": "5-10", "max_split": 100}
    assert core["mux"] == {"enabled": True, "concurrency": 4, "xudp_concurrency": 32,
                           "xudp_proxy_udp443": "allow"}
    assert core["sniffing"] == {"enabled": False, "route_only": True}
    assert core["socks_port"] == 23456
    assert core["allow_lan"] is True
    assert core["lan_user"] == "u1" and core["lan_pass"] == "p1"
    assert core["default_fp"] == "chrome"
    assert win.values()["startup"] == {
        "start_on_login": False, "start_minimized": True, "auto_connect": True,
    }


def test_settings_window_editing_never_touches_the_callers_settings(qapp, defaults):
    win = SettingsWindow(defaults)
    win._pages["general"].tun_mtu.setValue(1280)
    win._pages["language"].language.setCurrentIndex(
        win._pages["language"].language.findData("fa"))
    # Nothing written until Done, and the caller's dict is never written at all.
    assert defaults["tun_mtu"] == 1420
    assert defaults.get("language") == "en"


def test_settings_window_lan_warning_shows_only_without_a_password(qapp, defaults):
    win = SettingsWindow(defaults)
    page = win._pages["local-proxy"]
    assert page.lan_warning.isHidden()
    page.allow_lan.setChecked(True)
    assert not page.lan_warning.isHidden()
    page.lan_user.setText("u1")
    page.lan_pass.setText("p1")
    assert page.lan_warning.isHidden()
    page.lan_pass.setText("")
    assert not page.lan_warning.isHidden()


# -- Done (validation + apply) ----------------------------------------------
def test_done_applies_and_accepts(qapp, defaults, check_ok):
    win = SettingsWindow(defaults)
    win._pages["general"].tun_mtu.setValue(1280)
    _done_and_wait(win)
    assert win.result() == 1
    assert defaults["tun_mtu"] == 1420  # caller dict untouched
    assert win.values()["tun_mtu"] == 1280


def test_done_blocked_by_a_check_failure_shows_reason_inline_and_keeps_window_open(
    qapp, defaults, monkeypatch,
):
    monkeypatch.setattr(sw_mod.xraycheck, "check_config", lambda *a, **k: "simulated failure")
    win = SettingsWindow(defaults)
    win._pages["local-proxy"].socks_port.setValue(23456)
    _done_and_wait(win)
    assert win.result() == 0
    assert not win._status_label.isHidden()
    assert "simulated failure" in win._status_label.text()
    assert defaults["core"]["socks_port"] == 10808
    assert win.values()["core"]["socks_port"] == 23456  # still staged, not saved


def test_done_reports_an_exception_in_validation(qapp, defaults, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("xray -test crashed")
    monkeypatch.setattr(sw_mod.xraycheck, "check_config", boom)
    win = SettingsWindow(defaults)
    _done_and_wait(win)
    assert win.result() == 0
    assert not win._status_label.isHidden()
    assert "xray -test crashed" in win._status_label.text()


def test_reject_discards_staged_edits(qapp, defaults):
    win = SettingsWindow(defaults)
    win._pages["general"].tun_mtu.setValue(1280)
    win.reject()
    assert win.result() == 0
    assert defaults["tun_mtu"] == 1420


def test_enter_in_a_line_edit_triggers_done(qapp, defaults, monkeypatch):
    monkeypatch.setattr(sw_mod.xraycheck, "check_config", lambda *a, **k: None)
    win = SettingsWindow(defaults)
    win.show()
    qapp.processEvents()
    win.activateWindow()
    win._pages["general"].ping_target.setFocus()
    qapp.processEvents()
    QTest.keyClick(win._pages["general"].ping_target, Qt.Key_Return)
    _pump(lambda: not win._busy)
    win.close()
    assert win.result() == 1


# -- Startup, updates, geo, backup/restore ----------------------------------
def test_start_on_login_disabled_with_reason_when_unsupported(qapp, defaults, monkeypatch):
    monkeypatch.setattr(sw_mod.autostart, "is_supported",
                        lambda: (False, "Install the .deb package to start sushTun at login."))
    win = SettingsWindow(defaults)
    page = win._pages["startup"]
    assert not page.start_on_login.isEnabled()
    assert page.start_on_login.toolTip() == "Install the .deb package to start sushTun at login."


def test_start_on_login_enabled_when_supported(qapp, defaults, monkeypatch):
    monkeypatch.setattr(sw_mod.autostart, "is_supported", lambda: (True, ""))
    win = SettingsWindow(defaults)
    assert win._pages["startup"].start_on_login.isEnabled()


def test_done_enables_autostart_when_toggled_on(qapp, defaults, check_ok, monkeypatch):
    monkeypatch.setattr(sw_mod.autostart, "is_supported", lambda: (True, ""))
    calls = []
    monkeypatch.setattr(sw_mod.autostart, "enable", lambda: calls.append("enable"))
    monkeypatch.setattr(sw_mod.autostart, "disable", lambda: calls.append("disable"))

    win = SettingsWindow(defaults)
    win._pages["startup"].start_on_login.setChecked(True)
    _done_and_wait(win)

    assert calls == ["enable"]
    assert win.result() == 1


def test_done_shows_an_inline_error_when_enabling_autostart_fails(
    qapp, defaults, check_ok, monkeypatch,
):
    monkeypatch.setattr(sw_mod.autostart, "is_supported", lambda: (True, ""))

    def raise_enable():
        raise RuntimeError("could not write the polkit rule")

    monkeypatch.setattr(sw_mod.autostart, "enable", raise_enable)

    win = SettingsWindow(defaults)
    win._pages["startup"].start_on_login.setChecked(True)
    _done_and_wait(win)

    assert win.result() == 0
    assert not win._status_label.isHidden()
    assert "polkit rule" in win._status_label.text()


def test_geo_update_now_success_sets_last_update_and_status(qapp, defaults, tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(sw_mod.app_settings.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(sw_mod.geo_mod, "update", lambda source, fetch=None: None)
    win = SettingsWindow(defaults)
    page = win._pages["geo-data"]
    assert page.geo_status.text() == "Never updated"

    page._update_geo_now()
    _pump(lambda: not page._geo_busy)

    assert win.geo_updated()
    assert page.geo_status.text() != "Never updated"
    assert win.values()["geo"]["last_update"] > 0


def test_geo_update_now_persists_the_source_alongside_last_update(qapp, defaults, tmp_path,
                                                                  monkeypatch):
    # A successful Update now already swapped real files on disk for that
    # source; if the user then hits Cancel, settings must not claim a
    # different source produced those files.
    monkeypatch.setattr(sw_mod.app_settings.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(sw_mod.geo_mod, "update", lambda source, fetch=None: None)
    win = SettingsWindow(defaults)
    page = win._pages["geo-data"]
    page.geo_source.setCurrentText("Chocolate4U (Iran)")

    page._update_geo_now()
    _pump(lambda: not page._geo_busy)

    saved = sw_mod.app_settings.load()
    assert saved["geo"]["source"] == "Chocolate4U (Iran)"
    assert saved["geo"]["last_update"] > 0


def test_geo_update_now_failure_shows_inline_no_popup(qapp, defaults, tmp_path, monkeypatch):
    monkeypatch.setattr(sw_mod.app_settings.paths, "base_dir", lambda: tmp_path)

    def fake_update(source, fetch=None):
        raise sw_mod.geo_mod.GeoUpdateError("new geo data rejected: bad category")

    monkeypatch.setattr(sw_mod.geo_mod, "update", fake_update)
    popups = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: popups.append(a) or None), raising=False)

    win = SettingsWindow(defaults)
    page = win._pages["geo-data"]
    page._update_geo_now()
    _pump(lambda: not page._geo_busy)

    assert not win.geo_updated()
    assert "bad category" in page.geo_status.text()
    assert popups == []
    assert page.btn_geo_update.isEnabled()


def test_backup_button_writes_a_zip_and_confirms(qapp, defaults, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    paths.ensure_dirs()
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    dest = tmp_path / "out.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(dest), "")), raising=False)
    infos = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: infos.append(a) or None), raising=False)

    win = SettingsWindow(defaults)
    page = win._pages["backup"]
    page._backup_now()
    _pump(lambda: not page._backup_busy)

    assert dest.exists()
    assert infos
    assert not win.restored()


def test_restore_button_round_trips_and_flags_restored(qapp, defaults, tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(paths, "base_dir", lambda: src)
    paths.ensure_dirs()
    (src / "settings.json").write_text('{"marker": "from-backup"}', encoding="utf-8")
    zip_path = tmp_path / "backup.zip"
    sw_mod.backup_mod.backup(zip_path)

    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(paths, "base_dir", lambda: dest)
    paths.ensure_dirs()

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(zip_path), "")), raising=False)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes), raising=False)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None), raising=False)

    win = SettingsWindow(defaults)
    page = win._pages["backup"]
    page._restore_now()

    assert win.restored()
    assert json.loads((dest / "settings.json").read_text()) == {"marker": "from-backup"}

@pytest.mark.parametrize("lang", ["en", "fa"])
def test_sidebar_names_are_not_elided(qapp, defaults, lang):
    from PySide6.QtCore import Qt

    from xrayui.i18n import set_language
    from xrayui.ui.settings_window import SettingsSidebarItem
    set_language(lang)
    direction = Qt.RightToLeft if lang == "fa" else Qt.LeftToRight
    qapp.setLayoutDirection(direction)
    try:
        win = SettingsWindow(defaults)
        win.resize(820, 560)
        win.show()
        qapp.processEvents()
        items = win.findChildren(SettingsSidebarItem)
        assert items
        for item in items:
            assert item.visible_text() == item.text(), item.text()
        win.close()
    finally:
        qapp.setLayoutDirection(Qt.LeftToRight)
        set_language("en")

def test_topic_icons_are_distinct_and_done_is_primary(qapp, defaults):
    from xrayui.ui.icons import icon
    from xrayui.ui.settings_window import TOPICS
    names = [name for _key, _label, name, _color in TOPICS]
    assert len(set(names)) == len(names), names
    for name in names:
        assert not icon(name).isNull()
    from xrayui.ui.settings_window import SettingsWindow
    win = SettingsWindow(defaults)
    try:
        assert win.btn_done.objectName() == "Primary"
        assert win.btn_done.isDefault()
    finally:
        win.close()


def test_topic_rows_do_not_overlap_in_persian(qapp, defaults):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    from xrayui.i18n import set_language
    set_language("fa")
    qapp.setLayoutDirection(Qt.RightToLeft)
    try:
        win = SettingsWindow(defaults)
        win.resize(820, 560)
        win.show()
        qapp.processEvents()
        win._select_topic("anti-filter")
        qapp.processEvents()
        page = win._pages["anti-filter"]
        rows = [w for w in page.findChildren(QWidget) if w.objectName() == "InsetGroupRow"]
        assert rows
        for row in rows:
            assert row.height() >= row.minimumHeight(), row.height()
        win.close()
    finally:
        qapp.setLayoutDirection(Qt.LeftToRight)
        set_language("en")


def test_close_light_cancels_and_the_buttons_have_a_gap(qapp, defaults):
    import sys

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    from xrayui.i18n import tr
    win = SettingsWindow(defaults)
    try:
        win.resize(820, 560)
        win.show()
        qapp.processEvents()
        cancel = next(b for b in win.findChildren(QPushButton) if b.text() == tr("Cancel"))
        assert win.btn_done.x() - (cancel.x() + cancel.width()) >= 8
        if sys.platform == "darwin":
            return
        assert win.windowFlags() & Qt.FramelessWindowHint
        rejected = []
        win.rejected.connect(lambda: rejected.append(True))
        win.btn_close.click()
        assert rejected == [True]
    finally:
        win.close()


def test_settings_window_tcp_tuning_persists(qapp, defaults, monkeypatch):
    monkeypatch.setattr(sw_mod.coreopts, "available_tcp_congestion", lambda: ["reno", "cubic"])
    win = SettingsWindow(defaults)
    page = win._pages["anti-filter"]
    assert page.tcp_congestion.currentData() == ""  # system default
    page.tcp_fast_open.setChecked(True)
    page.tcp_mptcp.setChecked(True)
    page.tcp_congestion.setCurrentIndex(page.tcp_congestion.findData("cubic"))
    assert win.values()["core"]["sockopt"] == {
        "tcp_fast_open": True, "tcp_mptcp": True, "tcp_congestion": "cubic"}


def test_settings_window_hides_congestion_without_a_kernel_list(qapp, defaults, monkeypatch):
    monkeypatch.setattr(sw_mod.coreopts, "available_tcp_congestion", lambda: [])
    page = SettingsWindow(defaults)._pages["anti-filter"]
    assert page.tcp_congestion.parent() is None or page.tcp_congestion.isHidden()
    assert SettingsWindow(defaults).values()["core"]["sockopt"]["tcp_congestion"] == ""


def test_settings_window_udp_noise_persists(qapp, defaults):
    page = SettingsWindow(defaults)._pages["anti-filter"]
    assert not page.noise_enabled.isChecked()
    page.noise_enabled.setChecked(True)
    page.noise_length.setText("20-40")
    page.noise_delay.setText("5-10")
    assert page.collect()["udp_noise"] == {"enabled": True, "length": "20-40", "delay": "5-10"}


# -- Multi-exit port page -------------------------------------------------------------
def _servers():
    from xrayui.core.profiles import Profile
    return [Profile(uid="de1", name="Germany", protocol="vless", address="de.example",
                    port=443, id="u"),
            Profile(uid="nl1", name="NL", protocol="vless", address="203.0.113.9",
                    port=443, id="u")]


def test_exits_page_is_off_with_a_password_ready(qapp, defaults):
    page = SettingsWindow(defaults, profiles=_servers())._pages["exits"]
    got = page.collect()
    assert got["enabled"] is False and got["port"] == 10809 and got["items"] == []
    assert len(got["password"]) >= 8  # made for the user, saved on Done
    assert page.problem() is None      # off: nothing to check


def test_exits_page_saves_rows(qapp, defaults):
    win = SettingsWindow(defaults, profiles=_servers())
    page = win._pages["exits"]
    page.enabled.setChecked(True)
    page.btn_add.click()
    page.btn_add.click()
    (_r1, name1, server1), (_r2, name2, server2) = page._rows
    name1.setText("de")
    server1.setCurrentIndex(server1.findData("de1"))
    name2.setText("nl")
    server2.setCurrentIndex(server2.findData("nl1"))
    assert page.problem() is None
    assert win.values()["exits"]["items"] == [{"user": "de", "profile_uid": "de1"},
                                              {"user": "nl", "profile_uid": "nl1"}]


def test_exits_page_remove_drops_the_row(qapp, defaults):
    page = SettingsWindow(defaults, profiles=_servers())._pages["exits"]
    page.btn_add.click()
    row, _name, _server = page._rows[0]
    row.findChild(QAbstractButton).click()
    assert page._rows == [] and page.collect()["items"] == []


@pytest.mark.parametrize("items,port,reason", [
    ([], 10809, "at least one exit"),
    ([{"user": "de", "profile_uid": "de1"}, {"user": "de", "profile_uid": "nl1"}],
     10809, "used twice"),
    ([{"user": "De!", "profile_uid": "de1"}], 10809, "not a valid username"),
    ([{"user": "de", "profile_uid": "de1"}], 10808, "already used by sushTun"),
])
def test_exits_page_refuses_bad_values_while_on(qapp, defaults, items, port, reason):
    defaults["exits"].update(enabled=True, port=port, password="pw123456", items=items)
    win = SettingsWindow(defaults, profiles=_servers())
    assert reason in win._pages["exits"].problem()
    win._on_done()
    assert not win._busy
    assert reason in win._status_label.text()


def test_exits_page_marks_a_deleted_server(qapp, defaults):
    defaults["exits"].update(enabled=True, items=[{"user": "de", "profile_uid": "gone"}])
    page = SettingsWindow(defaults, profiles=_servers())._pages["exits"]
    _row, _name, server = page._rows[0]
    assert server.currentData() == "gone"
    assert "no longer exists" in page.problem()


def test_exits_page_warns_about_host_names_with_remote_dns(qapp, defaults):
    defaults["dns"]["remote_via_tunnel"] = True
    defaults["exits"]["items"] = [{"user": "nl", "profile_uid": "nl1"}]
    page = SettingsWindow(defaults, profiles=_servers())._pages["exits"]
    assert page.dns_warning.isHidden()          # an IP address needs no lookup
    _row, _name, server = page._rows[0]
    server.setCurrentIndex(server.findData("de1"))
    assert not page.dns_warning.isHidden()       # de.example is a host name


# -- Hotspot page -------------------------------------------------------------------
def test_hotspot_page_keeps_the_on_off_keys_and_saves_the_options(qapp, defaults, monkeypatch):
    monkeypatch.setattr(sw_mod.sys, "platform", "linux")
    defaults["gateway"].update(enabled=True, start_hotspot=False, password="joinme123")
    win = SettingsWindow(defaults)
    page = win._pages["hotspot"]
    assert page.password.echoMode() == page.password.EchoMode.Password
    page.btn_show.setChecked(True)
    assert page.password.echoMode() == page.password.EchoMode.Normal
    page.ssid.setText("Home AP")
    page.security.setCurrentIndex(page.security.findData("wpa3"))
    page.band.setCurrentIndex(page.band.findData("a"))
    page.hidden.setChecked(True)
    page.isolation.setChecked(True)
    assert win.values()["gateway"] == {
        "enabled": True, "start_hotspot": False, "ssid": "Home AP", "password": "joinme123",
        "security": "wpa3", "band": "a", "hidden": True, "isolation": True}


def test_hotspot_page_new_makes_a_valid_password(qapp, defaults, monkeypatch):
    monkeypatch.setattr(sw_mod.sys, "platform", "linux")
    page = SettingsWindow(defaults)._pages["hotspot"]
    page.btn_new.click()
    assert 8 <= len(page.password.text()) <= 63
    assert page.problem() is None


@pytest.mark.parametrize("ssid,password,ok", [
    ("sushTun", "", True),              # empty: made on the first start
    ("sushTun", "joinme123", True),
    ("", "joinme123", False),
    ("x" * 33, "joinme123", False),
    ("sushTun", "short", False),
    ("sushTun", "x" * 64, False),
    ("sushTun", "رمزعبور۱۲۳", False),   # WPA passphrases are plain ASCII
])
def test_hotspot_page_validation(qapp, defaults, monkeypatch, ssid, password, ok):
    monkeypatch.setattr(sw_mod.sys, "platform", "linux")
    page = SettingsWindow(defaults)._pages["hotspot"]
    page.ssid.setText(ssid)
    page.password.setText(password)
    assert (page.problem() is None) == ok


def test_done_is_refused_while_the_hotspot_page_is_invalid(qapp, defaults, monkeypatch, check_ok):
    monkeypatch.setattr(sw_mod.sys, "platform", "linux")
    win = SettingsWindow(defaults)
    win._pages["hotspot"].password.setText("short")
    win._on_done()
    assert not win._busy
    assert "8 to 63" in win._status_label.text()


def test_hotspot_page_on_windows_only_explains(qapp, defaults, monkeypatch):
    monkeypatch.setattr(sw_mod.sys, "platform", "win32")
    win = SettingsWindow(defaults)
    page = win._pages["hotspot"]
    page.ssid.setText("")  # disabled there; must not block Done or change anything
    assert page.problem() is None
    assert win.values()["gateway"] == defaults["gateway"]




# -- General → Check now ----------------------------------------------------

def _general(win):
    return win._pages["general"]


def test_check_now_says_when_there_is_nothing_to_do(qapp, defaults, monkeypatch):
    """Silence after pressing a button reads as a broken button."""
    from xrayui import __version__

    win = SettingsWindow(defaults)
    try:
        page = _general(win)
        page._on_checked(sw_mod.updates_mod.Release(tag=f"v{__version__}", url="https://x"))
        assert "up to date" in page.update_status.text().lower()
        assert page.btn_check_now.isEnabled()
    finally:
        win.close()


def test_check_now_reports_a_failure_instead_of_going_quiet(qapp, defaults):
    win = SettingsWindow(defaults)
    try:
        page = _general(win)
        page._on_checked(None)
        assert page.update_status.text()
        assert page.btn_check_now.isEnabled()
    finally:
        win.close()


def test_a_found_release_is_handed_to_the_window_not_installed_here(qapp, defaults):
    """Installing means quitting the app, which only the main window can do."""
    win = SettingsWindow(defaults)
    seen = []
    win.updateAvailable.connect(seen.append)
    try:
        release = sw_mod.updates_mod.Release(tag="v99.0.0", url="https://x")
        _general(win)._on_checked(release)
        assert [r.tag for r in seen] == ["v99.0.0"]
        assert "v99.0.0" in _general(win).update_status.text()
    finally:
        win.close()
