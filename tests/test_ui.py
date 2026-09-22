"""UI smoke tests: the dialogs and the main window actually construct and round-trip.

Skipped when PySide6 is missing so a contributor without it still gets a green
suite -- except under CI, where a skip must fail instead. A silent skip reads
exactly like a pass in the run summary, and that is how the UI came to be the
one part of the app no test ever executed.
"""
from __future__ import annotations

import copy
import json
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

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import dns as dns_mod  # noqa: E402
from xrayui.core import hotspot as hotspot_mod  # noqa: E402
from xrayui.core import network as network_mod  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.core import speedtest as speedtest_mod  # noqa: E402
from xrayui.core import updates as updates_mod  # noqa: E402
from xrayui.core.profiles import Profile  # noqa: E402
from xrayui.core.subscription import Subscription  # noqa: E402
from xrayui.i18n import ltr  # noqa: E402
from xrayui.ui import dialogs as dialogs_mod  # noqa: E402
from xrayui.ui.dialogs import (  # noqa: E402
    ProfileEditDialog,
    SettingsDialog,
    SubscriptionEditDialog,
)
from xrayui.ui.dns_dialog import DnsDialog  # noqa: E402
from xrayui.ui.server_table import COL_DELAY  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def defaults():
    return copy.deepcopy(app_settings.DEFAULTS)


class _NoSignal:
    """Stands in for SettingsWindow.updateAvailable in the fake dialogs below."""

    def connect(self, *_args, **_kwargs):
        pass


@pytest.fixture
def warnings(monkeypatch):
    """Capture QMessageBox.warning text instead of blocking on a modal."""
    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: seen.append(a[2])), raising=False)
    return seen


# -- DNS dialog ------------------------------------------------------------
def _save_and_wait(dlg) -> None:
    dlg._save()
    _pump(lambda: not dlg._busy)


@pytest.fixture
def dns_check_state(tmp_path, monkeypatch):
    """Save renders a real config and validates it; point the throwaway
    config file at tmp_path instead of the real state dir (may be owned by
    a previous elevated run and not writable here), and stub out the real
    `xray run -test` call so these Save round-trips don't depend on a
    bundled xray binary being present (CI doesn't run fetch_deps -- see
    tests/test_xraycheck.py for real-binary coverage of check_config
    itself, skip-guarded there). A test that specifically needs Save to
    fail overrides this stub locally, after requesting the fixture."""
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(dialogs_mod.xraycheck, "check_config", lambda *a, **k: None)
    return tmp_path


def test_dns_dialog_empty_round_trip_keeps_the_inherit_contract(qapp, defaults):
    out = DnsDialog(defaults["dns"], defaults["routing"]).result_dns()
    assert out["servers"] == []
    assert out["hosts"] == []
    assert out["query_strategy"] == ""
    # Empty must mean "inherit the template", never an empty server list.
    assert dns_mod.build_dns(out) == {}


def test_dns_dialog_preset_fills_and_round_trips(qapp, defaults, warnings, dns_check_state):
    dlg = DnsDialog(defaults["dns"], defaults["routing"])
    dlg._fill(dns_mod.PRESETS["Quad9"])
    dlg.strategy.setCurrentIndex(dlg.strategy.findData("UseIPv4"))
    dlg.hosts.setPlainText("a.com = 1.2.3.4")
    _save_and_wait(dlg)

    assert not warnings
    out = dlg.result_dns()
    assert out["servers"] == dns_mod.PRESETS["Quad9"]
    assert out["query_strategy"] == "UseIPv4"
    # And the saved shape survives into the rendered Xray config.
    built = dns_mod.build_dns(out)
    assert built["servers"] == dns_mod.PRESETS["Quad9"]
    assert built["hosts"] == {"a.com": "1.2.3.4"}


def test_dns_dialog_reloads_what_it_saved(qapp, defaults, warnings, dns_check_state):
    first = DnsDialog(defaults["dns"], defaults["routing"])
    first._fill(["1.1.1.1"])
    first.hosts.setPlainText("a.com = 1.2.3.4")
    _save_and_wait(first)
    assert not warnings
    saved = first.result_dns()

    second = DnsDialog(saved, defaults["routing"])
    assert second.servers.toPlainText().splitlines() == ["1.1.1.1"]
    assert second.hosts.toPlainText().splitlines() == ["a.com = 1.2.3.4"]


def test_dns_dialog_accepts_a_valid_server(qapp, defaults, warnings, dns_check_state):
    dlg = DnsDialog(defaults["dns"], defaults["routing"])
    dlg.servers.setPlainText("https://1.1.1.1/dns-query")
    _save_and_wait(dlg)
    assert not warnings
    assert dlg.result() == 1


def test_dns_dialog_domestic_preset_fills_the_field(qapp, defaults):
    dlg = DnsDialog(defaults["dns"], defaults["routing"])
    dlg._fill_domestic(dns_mod.DOMESTIC_PRESETS["Shecan"])
    assert dlg.domestic.text() == "178.22.122.100, 185.51.200.2"
    dlg._fill_domestic([])
    assert dlg.domestic.text() == ""


def test_dns_dialog_note_follows_the_remote_via_tunnel_checkbox(qapp, defaults):
    dlg = DnsDialog(defaults["dns"], defaults["routing"])
    assert "your normal connection, not the tunnel" in dlg.note.text()
    dlg.remote_via_tunnel.setChecked(True)
    assert "go through the tunnel" in dlg.note.text()
    dlg.remote_via_tunnel.setChecked(False)
    assert "your normal connection, not the tunnel" in dlg.note.text()


def test_dns_dialog_advanced_and_domestic_fields_round_trip(qapp, defaults, warnings,
                                                             dns_check_state):
    dlg = DnsDialog(defaults["dns"], defaults["routing"])
    dlg._fill_domestic(dns_mod.DOMESTIC_PRESETS["Shecan"])
    dlg.remote_via_tunnel.setChecked(True)
    dlg.parallel_query.setChecked(True)
    dlg.serve_stale.setChecked(True)
    dlg.servers.setPlainText("1.1.1.1")
    _save_and_wait(dlg)

    assert not warnings
    out = dlg.result_dns()
    assert out["domestic_servers"] == ["178.22.122.100", "185.51.200.2"]
    assert out["remote_via_tunnel"] is True
    assert out["parallel_query"] is True
    assert out["serve_stale"] is True

    reloaded = DnsDialog(out, defaults["routing"])
    assert reloaded.domestic.text() == "178.22.122.100, 185.51.200.2"
    assert reloaded.remote_via_tunnel.isChecked()
    assert reloaded.parallel_query.isChecked()
    assert reloaded.serve_stale.isChecked()


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


def test_geo_update_now_persists_the_source_alongside_last_update(qapp, defaults, tmp_path,
                                                                    monkeypatch):
    # A successful Update now already swapped real files on disk for that
    # source; if the user then hits Cancel, settings must not claim a
    # different source produced those files.
    monkeypatch.setattr(dialogs_mod.app_settings.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(dialogs_mod.geo_mod, "update", lambda source, fetch=None: None)
    dlg = SettingsDialog(defaults)
    dlg.geo_source.setCurrentText("Chocolate4U (Iran)")

    dlg._update_geo_now()
    _pump(lambda: not dlg._geo_busy)

    saved = dialogs_mod.app_settings.load()
    assert saved["geo"]["source"] == "Chocolate4U (Iran)"
    assert saved["geo"]["last_update"] > 0


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


def test_settings_dialog_advanced_fields_persist(qapp, defaults, warnings, dns_check_state):
    dlg = SettingsDialog(defaults)
    dlg.frag_enabled.setChecked(True)
    dlg.frag_packets.setText("1-3")
    dlg.frag_length.setText("50-100")
    dlg.frag_interval.setText("5-10")
    dlg.frag_max_split.setValue(100)
    dlg.mux_enabled.setChecked(True)
    dlg.mux_concurrency.setValue(4)
    dlg.mux_xudp_concurrency.setValue(32)
    dlg.mux_xudp_udp443.setCurrentText("allow")
    dlg.sniff_enabled.setChecked(False)
    dlg.socks_port.setValue(23456)
    dlg.allow_lan.setChecked(True)
    dlg.lan_user.setText("u1")
    dlg.lan_pass.setText("p1")
    dlg.default_fp.setCurrentIndex(dlg.default_fp.findData("chrome"))
    _save_and_wait(dlg)

    assert not warnings
    core = dlg.values()["core"]
    assert core["fragment"] == {"enabled": True, "packets": "1-3", "length": "50-100",
                                "interval": "5-10", "max_split": 100}
    assert core["mux"] == {"enabled": True, "concurrency": 4, "xudp_concurrency": 32,
                           "xudp_proxy_udp443": "allow"}
    assert core["sniffing"] == {"enabled": False, "route_only": False}
    assert core["socks_port"] == 23456
    assert core["allow_lan"] is True
    assert core["lan_user"] == "u1" and core["lan_pass"] == "p1"
    assert core["default_fp"] == "chrome"


def test_settings_dialog_lan_warning_shows_only_without_a_password(qapp, defaults):
    dlg = SettingsDialog(defaults)
    assert dlg.lan_warning.isHidden()
    dlg.allow_lan.setChecked(True)
    assert not dlg.lan_warning.isHidden()
    dlg.lan_user.setText("u1")
    dlg.lan_pass.setText("p1")
    assert dlg.lan_warning.isHidden()
    dlg.lan_pass.setText("")
    assert not dlg.lan_warning.isHidden()


def test_settings_dialog_save_blocked_by_a_check_failure_leaves_settings_unchanged(
    qapp, defaults, warnings, monkeypatch,
):
    # Every core-option builder self-heals bad input rather than emitting
    # something xray -test would reject, so a real failure can't be
    # triggered through the dialog's own fields; force one at the
    # xraycheck layer instead, to prove Save still refuses to close on any
    # failure regardless of cause, and never touches the caller's settings.
    monkeypatch.setattr(dialogs_mod.xraycheck, "check_config", lambda *a, **k: "simulated failure")
    dlg = SettingsDialog(defaults)
    dlg.frag_enabled.setChecked(True)
    dlg.socks_port.setValue(23456)
    _save_and_wait(dlg)

    assert warnings
    assert dlg.result() == 0
    assert defaults["core"]["fragment"]["enabled"] is False
    assert defaults["core"]["socks_port"] == 10808


# -- Startup, backup/restore, updates (Phase 7a) -----------------------------
def test_settings_dialog_startup_and_updates_round_trip(qapp, defaults, monkeypatch):
    monkeypatch.setattr(dialogs_mod.autostart, "is_supported", lambda: (True, ""))
    dlg = SettingsDialog(defaults)
    dlg.start_minimized.setChecked(True)
    dlg.auto_connect.setChecked(True)
    dlg.check_updates.setChecked(False)

    values = dlg.values()
    assert values["startup"] == {
        "start_on_login": False,
        "start_minimized": True,
        "auto_connect": True,
    }
    assert values["updates"]["check"] is False


def test_settings_dialog_start_on_login_disabled_with_reason_when_unsupported(
    qapp, defaults, monkeypatch,
):
    monkeypatch.setattr(dialogs_mod.autostart, "is_supported",
                        lambda: (False, "Install the .deb package to start sushTun at login."))
    dlg = SettingsDialog(defaults)
    assert not dlg.start_on_login.isEnabled()
    assert dlg.start_on_login.toolTip() == "Install the .deb package to start sushTun at login."


def test_settings_dialog_start_on_login_enabled_when_supported(qapp, defaults, monkeypatch):
    monkeypatch.setattr(dialogs_mod.autostart, "is_supported", lambda: (True, ""))
    dlg = SettingsDialog(defaults)
    assert dlg.start_on_login.isEnabled()


def test_settings_dialog_save_enables_autostart_when_toggled_on(qapp, defaults, monkeypatch):
    monkeypatch.setattr(dialogs_mod.xraycheck, "check_config", lambda *a, **k: None)
    monkeypatch.setattr(dialogs_mod.autostart, "is_supported", lambda: (True, ""))
    calls = []
    monkeypatch.setattr(dialogs_mod.autostart, "enable", lambda: calls.append("enable"))
    monkeypatch.setattr(dialogs_mod.autostart, "disable", lambda: calls.append("disable"))

    dlg = SettingsDialog(defaults)
    dlg.start_on_login.setChecked(True)
    _save_and_wait(dlg)

    assert calls == ["enable"]
    assert dlg.result() == 1


def test_settings_dialog_save_shows_an_error_when_enabling_autostart_fails(
    qapp, defaults, warnings, monkeypatch,
):
    monkeypatch.setattr(dialogs_mod.xraycheck, "check_config", lambda *a, **k: None)
    monkeypatch.setattr(dialogs_mod.autostart, "is_supported", lambda: (True, ""))

    def raise_enable():
        raise RuntimeError("could not write the polkit rule")

    monkeypatch.setattr(dialogs_mod.autostart, "enable", raise_enable)

    dlg = SettingsDialog(defaults)
    dlg.start_on_login.setChecked(True)
    _save_and_wait(dlg)

    assert warnings
    assert "polkit rule" in warnings[-1]
    assert dlg.result() == 0


def test_settings_dialog_backup_button_writes_a_zip_and_confirms(
    qapp, defaults, tmp_path, monkeypatch,
):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    paths.ensure_dirs()
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    dest = tmp_path / "out.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(dest), "")), raising=False)
    infos = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: infos.append(a) or None), raising=False)

    dlg = SettingsDialog(defaults)
    dlg._backup_now()
    _pump(lambda: not dlg._backup_busy)

    assert dest.exists()
    assert infos
    assert not dlg.restored()


def test_settings_dialog_restore_button_round_trips_and_flags_restored(
    qapp, defaults, tmp_path, monkeypatch,
):
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setattr(paths, "base_dir", lambda: src)
    paths.ensure_dirs()
    (src / "settings.json").write_text('{"marker": "from-backup"}', encoding="utf-8")
    zip_path = tmp_path / "backup.zip"
    dialogs_mod.backup_mod.backup(zip_path)

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

    dlg = SettingsDialog(defaults)
    dlg._restore_now()

    assert dlg.restored()
    assert json.loads((dest / "settings.json").read_text()) == {"marker": "from-backup"}


def test_open_settings_reloads_profiles_and_tray_after_a_restore(window, monkeypatch):
    profile = window.store.save(Profile(name="stale", address="a.example.com",
                                        port=443, id="u"))
    window.store.set_active(profile.uid)
    window._reload_profiles()

    class FakeDialog:
        updateAvailable = _NoSignal()

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return 0

        def restored(self):
            return True

    monkeypatch.setattr("xrayui.ui.main_window.SettingsWindow", FakeDialog)
    monkeypatch.setattr(window.store, "list", lambda: [])
    monkeypatch.setattr(window.store, "active_uid", lambda: None)
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    reconnects = []
    monkeypatch.setattr(window, "_needs_reconnect", lambda what: reconnects.append(what))

    window._open_settings()

    assert window.profiles.model.rowCount() == 0
    assert reconnects == ["Settings restored from backup"]


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


@pytest.mark.parametrize("protocol,id_label,vmess_vis,ss_vis,vless_vis,stream_vis,wg_vis", [
    ("vless", "UUID", False, False, True, True, False),
    ("vmess", "UUID", True, False, False, True, False),
    ("trojan", "Password", False, False, False, True, False),
    ("shadowsocks", "Password", False, True, False, True, False),
    ("hysteria2", "Password", False, False, False, False, False),
    ("wireguard", "Private key", False, False, False, False, True),
])
def test_profile_edit_dialog_field_visibility_per_protocol(
    qapp, protocol, id_label, vmess_vis, ss_vis, vless_vis, stream_vis, wg_vis,
):
    p = Profile(name="p", protocol=protocol, address="a.com", port=443, id="u", pbk="pb")
    dlg = ProfileEditDialog(p)
    assert dlg._lab_id.text() == id_label
    assert not dlg.f_vmess_security.isHidden() == vmess_vis
    assert not dlg.f_ss_method.isHidden() == ss_vis
    assert not dlg.f_flow.isHidden() == vless_vis
    assert not dlg.f_encryption.isHidden() == vless_vis
    assert not dlg.f_network.isHidden() == stream_vis
    assert not dlg.f_wg_local.isHidden() == wg_vis
    assert not dlg._advanced.isHidden() == (not wg_vis)


def test_profile_edit_dialog_advanced_fields_round_trip(qapp):
    p = Profile(name="a", protocol="trojan", address="a.com", port=443, id="pw",
               network="xhttp")
    dlg = ProfileEditDialog(p)
    dlg.f_header_type.setText("http")
    dlg.f_xhttp_mode.setText("packet-up")
    dlg.f_xhttp_extra.setText('{"headers": {"X": "1"}}')
    dlg.f_ech.setText("ECHCONFIG")
    dlg.f_pcs.setText("ab" * 32)
    dlg.f_vcn.setText("a.com")
    dlg._save()
    saved = dlg.result_profile()
    assert saved.header_type == "http"
    assert saved.xhttp_mode == "packet-up"
    assert saved.xhttp_extra == '{"headers": {"X": "1"}}'
    assert saved.ech == "ECHCONFIG"
    assert saved.pcs == "ab" * 32
    assert saved.vcn == "a.com"


def test_profile_edit_dialog_has_no_allow_insecure_control(qapp):
    # The checkbox was removed (it silently did nothing against the
    # bundled Xray binary); the field itself must still survive Save
    # untouched, whichever way it started.
    assert not hasattr(ProfileEditDialog(
        Profile(name="a", protocol="trojan", address="a.com", port=443, id="pw")), "f_allow_insecure")

    on = Profile(name="a", protocol="trojan", address="a.com", port=443, id="pw",
                allow_insecure=True)
    dlg_on = ProfileEditDialog(on)
    dlg_on._save()
    assert dlg_on.result_profile().allow_insecure is True

    off = Profile(name="a", protocol="trojan", address="a.com", port=443, id="pw",
                 allow_insecure=False)
    dlg_off = ProfileEditDialog(off)
    dlg_off._save()
    assert dlg_off.result_profile().allow_insecure is False


def test_profile_edit_dialog_insecure_note_shown_and_advanced_expanded_only_when_set(qapp):
    on = ProfileEditDialog(Profile(name="a", protocol="vless", address="a.com", port=443,
                                   id="u", allow_insecure=True))
    assert not on.insecure_note.isHidden()

    off = ProfileEditDialog(Profile(name="b", protocol="vless", address="a.com", port=443,
                                    id="u", allow_insecure=False))
    assert off.insecure_note.isHidden()


@pytest.mark.parametrize("protocol,network,security,header_type,expect_visible,expect_hidden", [
    ("trojan", "xhttp", "tls", "", ["path", "host", "xhttp_mode", "xhttp_extra", "sni", "fp",
                                    "alpn", "ech", "pcs", "vcn"], ["sid", "spx", "service", "pbk"]),
    ("vless", "grpc", "tls", "", ["service", "sni", "fp", "alpn"],
     ["path", "host", "xhttp_mode", "sid", "spx"]),
    ("vless", "tcp", "reality", "", ["pbk", "sid", "spx", "sni", "fp"],
     ["alpn", "ech", "pcs", "vcn", "path", "host"]),
    ("shadowsocks", "tcp", "none", "http", ["header_type", "path", "host"],
     ["sni", "fp", "alpn", "xhttp_mode", "service"]),
])
def test_profile_edit_dialog_visibility_combinations(
    qapp, protocol, network, security, header_type, expect_visible, expect_hidden,
):
    p = Profile(name="p", protocol=protocol, address="a.com", port=443, id="u",
               network=network, security=security, header_type=header_type, pbk="pb")
    dlg = ProfileEditDialog(p)
    widgets = {
        "path": dlg.f_path, "host": dlg.f_host, "xhttp_mode": dlg.f_xhttp_mode,
        "xhttp_extra": dlg.f_xhttp_extra, "sni": dlg.f_sni, "fp": dlg.f_fp,
        "alpn": dlg.f_alpn, "ech": dlg.f_ech, "pcs": dlg.f_pcs, "vcn": dlg.f_vcn,
        "sid": dlg.f_sid, "spx": dlg.f_spx, "service": dlg.f_service, "pbk": dlg.f_pbk,
        "header_type": dlg.f_header_type,
    }
    for key in expect_visible:
        assert not widgets[key].isHidden(), f"{key} should be visible"
    for key in expect_hidden:
        assert widgets[key].isHidden(), f"{key} should be hidden"


def test_profile_edit_dialog_hysteria2_field_visibility(qapp):
    p = Profile(name="hy", protocol="hysteria2", address="a.com", port=443, id="pw")
    dlg = ProfileEditDialog(p)
    assert dlg._lab_id.text() == "Password"
    for widget in (dlg.f_sni, dlg.f_hy2_pcs, dlg.f_hy2_obfs_password,
                  dlg.f_hy2_ports, dlg.f_hy2_hop_interval,
                  dlg.f_hy2_up_mbps, dlg.f_hy2_down_mbps):
        assert not widget.isHidden(), widget
    for widget in (dlg.f_fp, dlg.f_alpn, dlg.f_network, dlg.f_security, dlg.f_pbk,
                  dlg.f_sid, dlg.f_spx, dlg.f_path, dlg.f_host, dlg.f_service,
                  dlg.f_encryption, dlg.f_flow, dlg.f_vmess_security, dlg.f_ss_method,
                  dlg.f_pcs, dlg.f_ech, dlg.f_vcn, dlg.f_header_type,
                  dlg.f_xhttp_mode, dlg.f_xhttp_extra):
        assert widget.isHidden(), widget
    assert not dlg._advanced.isHidden()


def test_profile_edit_dialog_hysteria2_fields_round_trip(qapp):
    p = Profile(name="hy", protocol="hysteria2", address="a.com", port=443, id="pw")
    dlg = ProfileEditDialog(p)
    dlg.f_sni.setText("a.com")
    dlg.f_hy2_pcs.setText("ab" * 32)
    dlg.f_hy2_obfs_password.setText("obfspass")
    dlg.f_hy2_ports.setText("20000-30000")
    dlg.f_hy2_hop_interval.setValue(45)
    dlg.f_hy2_up_mbps.setValue(100)
    dlg.f_hy2_down_mbps.setValue(50)
    dlg._save()
    saved = dlg.result_profile()
    assert saved.sni == "a.com"
    assert saved.pcs == "ab" * 32
    assert saved.hy2_obfs_password == "obfspass"
    assert saved.hy2_ports == "20000-30000"
    assert saved.hy2_hop_interval == "45"
    assert saved.hy2_up_mbps == 100
    assert saved.hy2_down_mbps == 50


def test_profile_edit_dialog_hysteria2_hop_interval_is_a_spinbox_zero_is_default(qapp):
    p = Profile(name="hy", protocol="hysteria2", address="a.com", port=443, id="pw",
               hy2_hop_interval="45")
    dlg = ProfileEditDialog(p)
    assert dlg.f_hy2_hop_interval.value() == 45
    dlg.f_hy2_hop_interval.setValue(0)
    dlg._save()
    assert dlg.result_profile().hy2_hop_interval == ""


def test_profile_edit_dialog_refuses_invalid_hysteria2_port_range(qapp, warnings):
    p = Profile(name="hy", protocol="hysteria2", address="a.com", port=443, id="pw")
    dlg = ProfileEditDialog(p)
    dlg.f_hy2_ports.setText("not-a-range")
    dlg._save()
    assert warnings
    assert dlg.result() == 0
    original = dlg.result_profile()
    assert original.hy2_ports == ""  # unchanged, Save was refused


def test_profile_edit_dialog_normalizes_hysteria2_port_range_on_save(qapp):
    p = Profile(name="hy", protocol="hysteria2", address="a.com", port=443, id="pw")
    dlg = ProfileEditDialog(p)
    dlg.f_hy2_ports.setText("20000:30000")
    dlg._save()
    assert dlg.result_profile().hy2_ports == "20000-30000"


def test_profile_edit_dialog_refuses_invalid_pinned_cert(qapp, warnings):
    p = Profile(name="hy", protocol="hysteria2", address="a.com", port=443, id="pw")
    dlg = ProfileEditDialog(p)
    dlg.f_hy2_pcs.setText("not-hex")
    dlg._save()
    assert warnings
    assert dlg.result() == 0

    p2 = Profile(name="v", protocol="vless", address="a.com", port=443, id="u",
                security="tls")
    dlg2 = ProfileEditDialog(p2)
    dlg2.f_pcs.setText("also-not-hex")
    dlg2._save()
    assert dlg2.result() == 0


def test_profile_edit_dialog_normalizes_pinned_cert_on_save(qapp):
    colon_form = ":".join(["AB"] * 32)
    p = Profile(name="v", protocol="vless", address="a.com", port=443, id="u",
               security="tls")
    dlg = ProfileEditDialog(p)
    dlg.f_pcs.setText(colon_form)
    dlg._save()
    assert dlg.result_profile().pcs == "ab" * 32


def test_profile_edit_dialog_refuses_invalid_xhttp_extra(qapp, warnings):
    p = Profile(name="a", protocol="trojan", address="a.com", port=443, id="pw",
               network="xhttp")
    dlg = ProfileEditDialog(p)
    dlg.f_xhttp_extra.setText("not json")
    dlg._save()
    assert warnings
    assert dlg.result() == 0
    dlg2 = ProfileEditDialog(p)
    dlg2.f_xhttp_extra.setText("[1, 2]")  # valid JSON, not an object
    dlg2._save()
    assert dlg2.result() == 0


def test_profile_edit_dialog_vmess_and_ss_credential_round_trip(qapp):
    p = Profile(name="v", protocol="vmess", address="a.com", port=443, id="uid-1")
    dlg = ProfileEditDialog(p)
    dlg.f_vmess_security.setCurrentText("chacha20-poly1305")
    dlg._save()
    assert dlg.result_profile().vmess_security == "chacha20-poly1305"

    p2 = Profile(name="s", protocol="shadowsocks", address="b.com", port=8388, id="pw")
    dlg2 = ProfileEditDialog(p2)
    dlg2.f_ss_method.setCurrentText("2022-blake3-aes-256-gcm")
    dlg2._save()
    assert dlg2.result_profile().ss_method == "2022-blake3-aes-256-gcm"


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
    assert window.sidebar.item_dns.text().startswith("DNS")
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
    assert window.profiles.model.data(idx) == ltr("77 ms")


# -- Routing combo / Reconnect now / tray submenu (Phase 2c) -----------------
def test_routing_combo_lists_sets_and_writes_mode(window):
    window.settings["routing"]["sets"] = [{"id": "s1", "name": "MySet", "rules": []}]
    window._refresh_routing_combo()
    assert [window.routing_combo.itemText(i) for i in range(window.routing_combo.count())] \
        == ["Simple", "MySet"]

    window.routing_combo.setCurrentIndex(window.routing_combo.findData("s1"))
    assert window.settings["routing"]["mode"] == "s1"


def test_anti_filter_button_toggles_and_persists(window):
    assert not window.btn_fragment.isChecked()
    assert not window.settings["core"]["fragment"]["enabled"]

    window.btn_fragment.setChecked(True)
    assert window.settings["core"]["fragment"]["enabled"] is True
    saved = app_settings.load()
    assert saved["core"]["fragment"]["enabled"] is True


def test_anti_filter_button_shows_reconnect_when_connected(window, monkeypatch):
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    window.btn_fragment.setChecked(True)
    assert not window.btn_reconnect.isHidden()
    assert "Anti-filter" in window.step_label.text()


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


def test_reconnect_now_connects_to_the_active_profile_not_the_selected_row(window, monkeypatch):
    a = window.store.save(Profile(name="A", address="a.example.com", port=443, id="u1"))
    b = window.store.save(Profile(name="B", address="b.example.com", port=443, id="u2"))
    window.store.set_active(a.uid)
    window._reload_profiles()

    # Select row A -- a single selection also activates it (existing
    # behaviour), so store.active_uid() and current_uid() agree so far.
    row_a = window.profiles.model.row_of_uid(a.uid)
    window.profiles.table.selectRow(row_a)
    assert window.profiles.current_uid() == a.uid

    # Use fastest makes B active without disturbing the table selection --
    # this is exactly what diverges the two after the multi-select fix.
    window._use_fastest(b.uid)
    assert window.store.active_uid() == b.uid
    assert window.profiles.current_uid() == a.uid

    calls = []
    monkeypatch.setattr(window.conn, "disconnect", lambda: calls.append("disconnect"))
    monkeypatch.setattr(window.conn, "connect", lambda p: calls.append(("connect", p.uid)))
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)

    window._reconnect_now()
    _pump(lambda: not window._busy)

    assert calls == ["disconnect", ("connect", b.uid)]


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


# -- Tray servers submenu (Phase 7a) -----------------------------------------
def test_tray_servers_submenu_lists_active_server_checked_with_delay(window):
    from PySide6.QtWidgets import QMenu
    window.servers_menu = QMenu()
    a = window.store.save(Profile(name="A", address="a.example.com", port=443, id="u1"))
    window.store.save(Profile(name="B", address="b.example.com", port=443, id="u2"))
    window.store.set_active(a.uid)
    window._reload_profiles()
    window.results.set(a.uid, delay_ms=84.0, error=None, skipped=False)
    window._rebuild_servers_tray_menu()

    actions = window.servers_menu.actions()
    labels = [act.text() for act in actions]
    from xrayui.i18n import ltr
    assert labels == [f"A · {ltr('84 ms')}", "B"]
    assert actions[0].isChecked()
    assert not actions[1].isChecked()


def test_tray_servers_submenu_caps_at_twenty_and_follows_table_order(window):
    from PySide6.QtWidgets import QMenu
    window.servers_menu = QMenu()
    for i in range(25):
        window.store.save(Profile(name=f"s{i:02d}", address="a.example.com",
                                  port=443, id=f"u{i}"))
    window._reload_profiles()

    assert len(window.servers_menu.actions()) == 20
    labels = [a.text() for a in window.servers_menu.actions()]
    expected = [window.store.get(uid).name for uid in window.profiles.visible_uids()[:20]]
    assert labels == expected


def test_tray_servers_submenu_switching_activates_and_reconnects(window, monkeypatch):
    from PySide6.QtWidgets import QMenu
    window.servers_menu = QMenu()
    a = window.store.save(Profile(name="A", address="a.example.com", port=443, id="u1"))
    b = window.store.save(Profile(name="B", address="b.example.com", port=443, id="u2"))
    window.store.set_active(a.uid)
    window._reload_profiles()

    reconnects = []
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    monkeypatch.setattr(window, "_needs_reconnect", lambda what: reconnects.append(what))

    b_action = next(act for act in window.servers_menu.actions() if act.text() == "B")
    b_action.trigger()

    assert window.store.active_uid() == b.uid
    assert reconnects == ["Active server changed"]
    assert window.servers_menu.actions()[
        [a.text() for a in window.servers_menu.actions()].index("B")
    ].isChecked()


# -- Subscriptions (Phase 6) --------------------------------------------------
def test_subscription_edit_dialog_round_trips_all_fields(qapp, warnings):
    sub = Subscription(url="https://sub.example/x", name="My sub")
    dlg = SubscriptionEditDialog(sub)
    dlg.f_enabled.setChecked(False)
    dlg.f_auto_hours.setValue(12)
    dlg.f_name_filter.setText("germany")
    dlg.f_user_agent.setText("MyClient/1.0")
    dlg._save()
    assert not warnings
    assert dlg.result() == 1
    saved = dlg.result_subscription()
    assert saved.enabled is False
    assert saved.auto_update_hours == 12
    assert saved.name_filter == "germany"
    assert saved.user_agent == "MyClient/1.0"


def test_subscription_edit_dialog_refuses_a_bad_regex(qapp, warnings):
    sub = Subscription(url="https://sub.example/x", name="My sub")
    dlg = SubscriptionEditDialog(sub)
    dlg.f_name_filter.setText("[unterminated")
    dlg._save()
    assert warnings
    assert dlg.result() == 0


def test_subscription_edit_dialog_requires_a_url(qapp, warnings):
    dlg = SubscriptionEditDialog(Subscription())
    dlg._save()
    assert warnings
    assert dlg.result() == 0


def test_subscription_edit_dialog_autofills_name_from_url_host(qapp):
    dlg = SubscriptionEditDialog(Subscription())
    dlg.f_url.setText("https://sub.example.com/abc123")
    dlg._maybe_autofill_name(dlg.f_url.text())
    assert dlg.f_name.text() == "sub.example.com"


def test_add_sub_uses_the_edit_dialog(window, monkeypatch):
    created = {}

    class FakeDialog:
        def __init__(self, sub, parent=None):
            sub.name = "Added sub"
            sub.url = "https://sub.example/added"
            created["sub"] = sub

        def exec(self):
            return 1

        def result_subscription(self):
            return created["sub"]

    import xrayui.ui.main_window as main_window_mod
    monkeypatch.setattr(main_window_mod, "SubscriptionEditDialog", FakeDialog)
    monkeypatch.setattr(window, "_refresh_sub", lambda uid: None)
    window._add_sub()

    subs = window.subs.list()
    assert len(subs) == 1
    assert subs[0].name == "Added sub"
    assert subs[0].url == "https://sub.example/added"


def test_edit_button_and_double_click_open_the_editor_for_the_right_uid(window, monkeypatch):
    from xrayui.ui.pages.subscriptions_page import _PageSubscriptionRow as SubscriptionRow

    sub = Subscription(name="A sub", url="https://sub.example/x")
    window.subs.save(sub)
    window._reload_subs()

    seen = []
    # MainWindow.__init__ already connected subs_panel.editRequested to
    # _edit_sub; monkeypatching the attribute is enough, no extra connect.
    monkeypatch.setattr(window, "_edit_sub", lambda uid: seen.append(uid))

    row = window.subs_panel.findChild(SubscriptionRow)
    assert row.uid == sub.uid

    row.editRequested.emit(row.uid)
    assert seen == [sub.uid]

    seen.clear()
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    event = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    row.mouseDoubleClickEvent(event)
    assert seen == [sub.uid]


def test_disabled_sub_row_is_muted_and_meta_says_disabled(window):
    from PySide6.QtWidgets import QLabel

    from xrayui.ui.pages.subscriptions_page import _PageSubscriptionRow as SubscriptionRow

    window.subs.save(Subscription(name="Off sub", url="https://sub.example/x", enabled=False))
    window._reload_subs()
    row = window.subs_panel.findChild(SubscriptionRow)
    labels = row.findChildren(QLabel)
    name_label = next(lab for lab in labels if lab.text() == "Off sub")
    assert name_label.objectName() == "Muted"
    meta_label = next(lab for lab in labels if "updated" in lab.text())
    assert "disabled" in meta_label.text()


def test_update_all_skips_disabled_and_updates_sequentially(window, monkeypatch):
    order = []

    def fake_refresh(sub, profiles, subs_store):
        order.append(sub.uid)
        sub.updated = time.time()
        return sub

    monkeypatch.setattr("xrayui.ui.main_window.sub_mod.refresh", fake_refresh)
    on = Subscription(name="On", url="https://sub.example/on", enabled=True)
    off = Subscription(name="Off", url="https://sub.example/off", enabled=False)
    on2 = Subscription(name="On2", url="https://sub.example/on2", enabled=True)
    window.subs.save(on)
    window.subs.save(off)
    window.subs.save(on2)

    window._update_all_subs()
    _pump(lambda: not window._workers)

    assert order == [on.uid, on2.uid]
    assert "Updated 2 of 2 subscriptions" in window.step_label.text()


def test_update_all_reports_the_first_error(window, monkeypatch):
    def fake_refresh(sub, profiles, subs_store):
        if sub.name == "Bad":
            raise ValueError("boom")
        sub.updated = time.time()
        return sub

    monkeypatch.setattr("xrayui.ui.main_window.sub_mod.refresh", fake_refresh)
    window.subs.save(Subscription(name="Bad", url="https://sub.example/bad", enabled=True))
    window.subs.save(Subscription(name="Good", url="https://sub.example/good", enabled=True))

    window._update_all_subs()
    _pump(lambda: not window._workers)

    assert "Updated 1 of 2 subscriptions" in window.step_label.text()
    assert "boom" in window.step_label.text()


def test_update_all_with_no_enabled_subs_does_nothing(window, monkeypatch):
    called = []
    monkeypatch.setattr("xrayui.ui.main_window.sub_mod.refresh",
                        lambda *a, **k: called.append(1))
    window.subs.save(Subscription(name="Off", url="https://sub.example/off", enabled=False))

    window._update_all_subs()

    assert called == []
    assert "No enabled subscriptions" in window.step_label.text()


def test_auto_refresh_subs_uses_is_due_and_skips_disabled(window, monkeypatch):
    refreshed = []
    monkeypatch.setattr(window, "_refresh_sub", lambda uid: refreshed.append(uid))
    window.settings["alerts"]["auto_refresh_hours"] = 6

    due = Subscription(name="Due", url="https://sub.example/due", enabled=True, updated=0)
    not_due = Subscription(name="NotDue", url="https://sub.example/notdue",
                           enabled=True, updated=time.time())
    disabled = Subscription(name="Disabled", url="https://sub.example/disabled",
                            enabled=False, updated=0)
    window.subs.save(due)
    window.subs.save(not_due)
    window.subs.save(disabled)

    window._auto_refresh_subs()

    assert refreshed == [due.uid]


# -- --autostart launch behavior (Phase 7a) ----------------------------------
def test_starts_hidden_only_for_a_login_launch_with_start_minimized(defaults):
    from xrayui.ui.app import starts_hidden
    settings = copy.deepcopy(defaults)
    settings["startup"]["start_minimized"] = True
    assert starts_hidden(True, settings) is True
    # Opening it from the menu always shows the window.
    assert starts_hidden(False, settings) is False
    assert starts_hidden(True, defaults) is False
    assert starts_hidden(False, defaults) is False
    # No tray icon means a hidden window could never be reached.
    assert starts_hidden(True, settings, tray=False) is False


def test_auto_connect_on_startup_skips_quietly_with_no_profile(window, monkeypatch):
    window.settings["startup"]["auto_connect"] = True
    assert window.store.active_uid() is None
    calls = []
    monkeypatch.setattr(window.conn, "connect", lambda p: calls.append(p.uid))
    window._auto_connect_on_startup()
    assert calls == []


def test_auto_connect_on_startup_does_nothing_when_the_setting_is_off(window, monkeypatch):
    profile = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window.store.set_active(profile.uid)
    window._reload_profiles()
    assert not window.settings["startup"]["auto_connect"]

    calls = []
    monkeypatch.setattr(window.conn, "connect", lambda p: calls.append(p.uid))
    window._auto_connect_on_startup()
    assert calls == []


def test_auto_connect_on_startup_connects_once_the_network_is_up(window, monkeypatch):
    profile = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window.store.set_active(profile.uid)
    window._reload_profiles()
    window.settings["startup"]["auto_connect"] = True

    monkeypatch.setattr(network_mod, "detect_interface", lambda: SimpleNamespace(alias="eth0"))
    calls = []
    monkeypatch.setattr(window.conn, "connect", lambda p: calls.append(p.uid))

    window._auto_connect_on_startup()
    _pump(lambda: not window._busy)

    assert calls == [profile.uid]


def test_auto_connect_on_startup_retries_until_the_network_appears(window, monkeypatch):
    profile = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window.store.set_active(profile.uid)
    window._reload_profiles()
    window.settings["startup"]["auto_connect"] = True

    attempts = []

    def fake_detect():
        attempts.append(1)
        return None if len(attempts) < 3 else SimpleNamespace(alias="eth0")

    monkeypatch.setattr(network_mod, "detect_interface", fake_detect)
    import xrayui.ui.main_window as mw_mod
    monkeypatch.setattr(mw_mod.time, "sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(window.conn, "connect", lambda p: calls.append(p.uid))

    window._auto_connect_on_startup()
    _pump(lambda: not window._busy)

    assert len(attempts) == 3
    assert calls == [profile.uid]


def test_auto_connect_on_startup_gives_up_quietly_with_no_network(window, monkeypatch):
    profile = window.store.save(Profile(name="p", address="a.example.com", port=443, id="u"))
    window.store.set_active(profile.uid)
    window._reload_profiles()
    window.settings["startup"]["auto_connect"] = True

    monkeypatch.setattr(network_mod, "detect_interface", lambda: None)
    import xrayui.ui.main_window as mw_mod
    monkeypatch.setattr(mw_mod.time, "sleep", lambda s: None)
    clock = [0.0]

    def fake_monotonic():
        clock[0] += 30
        return clock[0]

    monkeypatch.setattr(mw_mod.time, "monotonic", fake_monotonic)
    calls = []
    monkeypatch.setattr(window.conn, "connect", lambda p: calls.append(p.uid))
    steps = []
    monkeypatch.setattr(window, "_on_step", lambda msg: steps.append(msg))

    window._auto_connect_on_startup()
    _pump(lambda: not window._busy)

    assert calls == []
    assert any("failed" in s.lower() for s in steps)


# -- Update check banner (Phase 7a) ------------------------------------------
def test_update_check_is_skipped_when_the_setting_is_off(window, monkeypatch):
    window.settings["updates"]["check"] = False
    window.settings["updates"]["last_check"] = 0
    called = []
    monkeypatch.setattr(updates_mod, "latest_release", lambda: called.append(1))
    window._maybe_check_updates()
    assert called == []


def test_update_check_is_skipped_when_checked_recently(window, monkeypatch):
    window.settings["updates"]["check"] = True
    window.settings["updates"]["last_check"] = time.time()
    called = []
    monkeypatch.setattr(updates_mod, "latest_release", lambda: called.append(1))
    window._maybe_check_updates()
    assert called == []


def test_update_check_runs_and_records_last_check_when_due(window, monkeypatch):
    window.settings["updates"]["check"] = True
    window.settings["updates"]["last_check"] = 0
    monkeypatch.setattr(updates_mod, "latest_release", lambda: None)
    window._maybe_check_updates()
    _pump(lambda: window.settings["updates"]["last_check"] != 0)
    assert window.settings["updates"]["last_check"] > 0


def _release(tag="v99.0.0"):
    return updates_mod.Release(
        tag=tag, url=f"https://example.com/releases/{tag}", notes="notes",
        assets={"sushTun-linux": "https://example.com/sushTun-linux"})


def test_update_check_offers_to_install_a_newer_version(window, monkeypatch):
    window.settings["updates"] = {"check": True, "last_check": 0, "notified_version": ""}
    opened = []
    monkeypatch.setattr(window, "open_update_dialog", lambda *a, **k: opened.append(True))
    window._on_update_checked(result=_release())
    assert not window.alert_banner.isHidden()
    assert "v99.0.0" in window.alert_banner._label.text()
    assert not window.alert_banner._action.isHidden()

    window.alert_banner._action.click()
    assert opened == [True]


def test_the_banner_action_hands_the_release_it_found_to_the_dialog(window, monkeypatch):
    """The banner is pressed long after the check ran, so the release has to
    have been kept -- otherwise the button opens an empty dialog."""
    window.settings["updates"] = {"check": True, "last_check": 0, "notified_version": ""}
    seen = []
    monkeypatch.setattr("xrayui.ui.update_dialog.run_update_flow",
                        lambda release, parent=None: seen.append(release) or False)
    window._on_update_checked(result=_release())
    window.alert_banner._action.click()
    assert [r.tag for r in seen] == ["v99.0.0"]


def test_the_app_quits_once_the_new_version_is_in_place(window, monkeypatch):
    """Quitting is the handover: it is what starts the new executable and
    what puts the routes and DNS back first."""
    quits = []
    monkeypatch.setattr("xrayui.ui.update_dialog.run_update_flow",
                        lambda release, parent=None: True)
    monkeypatch.setattr(window, "_quit", lambda: quits.append(True))
    window.open_update_dialog(_release())
    assert quits == [True]
    assert window.alert_banner.isHidden()


def test_nothing_happens_when_the_user_closes_the_update_dialog(window, monkeypatch):
    quits = []
    monkeypatch.setattr("xrayui.ui.update_dialog.run_update_flow",
                        lambda release, parent=None: False)
    monkeypatch.setattr(window, "_quit", lambda: quits.append(True))
    window.open_update_dialog(_release())
    assert quits == []


def test_update_check_shows_the_tray_toast_only_once_per_version(window):
    window.tray = _FakeTray()
    try:
        window.settings["updates"] = {"check": True, "last_check": 0, "notified_version": ""}
        window._on_update_checked(result=_release())
        assert len(window.tray.messages) == 1
        assert window.settings["updates"]["notified_version"] == "v99.0.0"

        window._on_update_checked(result=_release())
        assert len(window.tray.messages) == 1
    finally:
        window.tray = None


def test_update_check_ignores_a_non_newer_version(window):
    from xrayui import __version__ as _cur
    window.settings["updates"] = {"check": True, "last_check": 0, "notified_version": ""}
    # Same-or-older than the running version must not surface a banner.
    window._on_update_checked(result=_release(f"v{_cur}"))
    assert window.alert_banner.isHidden()


def test_update_check_does_nothing_on_fetch_failure(window):
    window.settings["updates"] = {"check": True, "last_check": 0, "notified_version": ""}
    window._on_update_checked(result=None)
    assert window.alert_banner.isHidden()
    assert window.settings["updates"]["last_check"] > 0


# -- Sidebar window shell (Direction A) --------------------------------------

def test_sidebar_nav_switches_the_page_stack(window):
    from xrayui.ui.main_window import PAGE_ACTIVITY, PAGE_DNS, PAGE_ROUTING
    assert window._stack.currentIndex() == 0  # Servers
    assert window.sidebar.item_servers.isChecked()
    assert window.sidebar.item_dns.text().startswith("DNS")

    window.sidebar.item_routing.click()
    assert window._stack.currentIndex() == PAGE_ROUTING
    assert window.sidebar.item_routing.isChecked()
    assert not window.sidebar.item_servers.isChecked()
    assert window.toolbar.title.text() == "Routing"

    window.sidebar.item_dns.click()
    assert window._stack.currentIndex() == PAGE_DNS
    assert window.sidebar.item_dns.isChecked()

    window.sidebar.item_activity.click()
    assert window._stack.currentIndex() == PAGE_ACTIVITY
    assert window.sidebar.item_activity.isChecked()


def test_nav_item_only_switches_to_a_different_page(window):
    from xrayui.ui.main_window import PAGE_ROUTING
    window._show_page(PAGE_ROUTING)
    # Clicking the already-active item must not reset anything or repaint the stack.
    window.sidebar.item_routing.click()
    assert window._stack.currentIndex() == PAGE_ROUTING


def test_ctrl_number_shortcuts_switch_pages(window):
    from PySide6.QtGui import QShortcut

    from xrayui.ui.main_window import PAGE_ACTIVITY, PAGE_DNS, PAGE_SERVERS
    by_key = {sc.key().toString(): sc for sc in window.findChildren(QShortcut)}
    assert {"Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5"} <= set(by_key)

    window._show_page(PAGE_SERVERS)
    assert window._stack.currentIndex() == PAGE_SERVERS

    by_key["Ctrl+4"].activated.emit()
    assert window._stack.currentIndex() == PAGE_DNS
    assert window.sidebar.item_dns.isChecked()

    by_key["Ctrl+5"].activated.emit()
    assert window._stack.currentIndex() == PAGE_ACTIVITY

    by_key["Ctrl+1"].activated.emit()
    assert window._stack.currentIndex() == PAGE_SERVERS


def test_servers_filter_is_shown_only_on_the_servers_page(window):
    from xrayui.ui.main_window import PAGE_ACTIVITY, PAGE_ROUTING
    assert not window.toolbar.filter_edit.isHidden()  # Servers
    window._show_page(PAGE_ROUTING)
    assert window.toolbar.filter_edit.isHidden()
    window._show_page(PAGE_ACTIVITY)
    assert window.toolbar.filter_edit.isHidden()
    window._show_page(0)
    assert not window.toolbar.filter_edit.isHidden()


def test_dirty_routing_page_blocks_switching_away(window, monkeypatch):
    from xrayui.ui.main_window import PAGE_ROUTING, PAGE_SERVERS
    window._show_page(PAGE_ROUTING)
    window._routing_page.proxy.setPlainText("example.com")
    assert window._routing_page.is_dirty()

    monkeypatch.setattr("xrayui.ui.main_window.confirm_leave", lambda *a: False)
    window._show_page(PAGE_SERVERS)
    assert window._stack.currentIndex() == PAGE_ROUTING
    assert window.sidebar.item_routing.isChecked()

    monkeypatch.setattr("xrayui.ui.main_window.confirm_leave", lambda *a: True)
    window._show_page(PAGE_SERVERS)
    assert window._stack.currentIndex() == PAGE_SERVERS


def test_dirty_dns_page_blocks_switching_away(window, monkeypatch):
    from xrayui.ui.main_window import PAGE_DNS, PAGE_SERVERS
    window._show_page(PAGE_DNS)
    window._dns_page.servers.setPlainText("8.8.8.8")
    assert window._dns_page.is_dirty()

    monkeypatch.setattr("xrayui.ui.main_window.confirm_leave", lambda *a: False)
    window._show_page(PAGE_SERVERS)
    assert window._stack.currentIndex() == PAGE_DNS

    monkeypatch.setattr("xrayui.ui.main_window.confirm_leave", lambda *a: True)
    window._show_page(PAGE_SERVERS)
    assert window._stack.currentIndex() == PAGE_SERVERS


def test_routing_popup_button_syncs_with_the_combo(window):
    window.settings["routing"]["sets"] = [{"id": "s1", "name": "MySet", "rules": []}]
    window._refresh_routing_combo()
    assert window.toolbar.btn_routing_popup.accessibleName() == "Routing: Simple"

    # Switching via the hidden combo updates the popup label.
    window.routing_combo.setCurrentIndex(window.routing_combo.findData("s1"))
    assert window.toolbar.btn_routing_popup.accessibleName() == "Routing: MySet"
    assert window.settings["routing"]["mode"] == "s1"

    # And a fresh refresh keeps the popup in step with the combo.
    window._refresh_routing_combo()
    assert window.toolbar.btn_routing_popup.accessibleName() == "Routing: MySet"


def test_routing_popup_menu_action_switches_the_mode(window):
    window.settings["routing"]["sets"] = [{"id": "s1", "name": "MySet", "rules": []}]
    window._refresh_routing_combo()
    menu = window.toolbar.btn_routing_popup.menu()
    assert menu is not None
    labels = [a.text() for a in menu.actions()]
    assert labels == ["Simple", "MySet"]


def test_hotspot_switch_persists_and_shows_the_detail(window):
    assert not window.settings["gateway"]["enabled"]
    window.sidebar.btn_gateway.setChecked(True)
    assert window.settings["gateway"]["enabled"] is True
    assert app_settings.load()["gateway"]["enabled"] is True
    assert not window.sidebar.hotspot_detail.isHidden()
    assert window.sidebar.hotspot_detail.text().startswith("SSID:")

    window.sidebar.btn_gateway.setChecked(False)
    assert window.settings["gateway"]["enabled"] is False
    assert window.sidebar.hotspot_detail.isHidden()
    assert "Hotspot sharing off." in window.step_label.text()


def test_subscription_count_reaches_the_sidebar(window):
    from xrayui.core.subscription import Subscription
    assert window.sidebar.item_subs._count is None
    s = Subscription(name="s1", url="https://x.example.com/s")
    window.subs.save(s)
    window._reload_subs()
    assert window.sidebar.item_subs._count == "1"


def test_subscription_edit_dialog_is_grouped_with_a_switch(qapp):
    from xrayui.ui.mac import InsetGroup, Switch
    sub = Subscription(name="Main", url="https://example.com/sub", enabled=False)
    dlg = SubscriptionEditDialog(sub)
    try:
        assert isinstance(dlg.f_enabled, Switch)
        assert not dlg.f_enabled.isChecked()
        assert len(dlg.findChildren(InsetGroup)) == 2
        assert dlg.f_enabled.accessibleName()
        dlg.f_enabled.setChecked(True)
        dlg._save()
        assert dlg.result_subscription().enabled is True
    finally:
        dlg.close()


def test_hotspot_password_shows_as_soon_as_the_switch_is_on(window, monkeypatch):
    monkeypatch.setattr(hotspot_mod, "IS_WIN", False)
    window.settings["gateway"]["password"] = ""
    window.sidebar.btn_gateway.setChecked(True)
    password = window.settings["gateway"]["password"]
    assert len(password) >= 8
    assert app_settings.load()["gateway"]["password"] == password
    assert window.sidebar.hotspot_detail.text().endswith(password)


def test_windows_hotspot_keeps_the_password_it_already_has(window, monkeypatch):
    """Windows' Mobile hotspot comes with a name and password of its own, and
    the switch must not quietly rewrite them with an invented one."""
    monkeypatch.setattr(hotspot_mod, "IS_WIN", True)
    window.settings["gateway"].update(ssid="", password="")
    window.sidebar.btn_gateway.setChecked(True)
    assert window.settings["gateway"]["password"] == ""
    assert app_settings.load()["gateway"]["enabled"] is True
    assert not window.sidebar.hotspot_detail.isVisible()


def test_hotspot_switch_starts_sharing_at_once_while_connected(window, monkeypatch):
    started = []
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    monkeypatch.setattr(window.conn, "start_gateway", lambda: started.append(True),
                        raising=False)
    monkeypatch.setattr(window, "_run_async", lambda fn, done: done(result=fn()))
    window.sidebar.btn_gateway.setChecked(True)
    assert started == [True]
    assert window.step_label.text() == "Hotspot is on."


def test_hotspot_that_fails_to_start_turns_the_switch_back_off(window, monkeypatch):
    monkeypatch.setattr(window.conn, "is_connected", lambda: True)
    monkeypatch.setattr(window.conn, "start_gateway", lambda: None, raising=False)
    monkeypatch.setattr(window, "_run_async",
                        lambda fn, done: done(error="hotspot did not start"))
    window.sidebar.btn_gateway.setChecked(True)
    assert not window.sidebar.btn_gateway.isChecked()
    assert window.settings["gateway"]["enabled"] is False
    assert app_settings.load()["gateway"]["enabled"] is False
    assert "hotspot did not start" in window.step_label.text()


def _pqv_key() -> str:
    import base64
    return base64.urlsafe_b64encode(bytes(1952)).rstrip(b"=").decode()


def test_profile_edit_dialog_round_trips_reality_pqv(qapp):
    p = Profile(name="r", address="a.com", port=443, id="u", network="tcp",
                security="reality", pbk="PUB", sid="ab", sni="a.com")
    dlg = ProfileEditDialog(p)
    assert not dlg.f_pqv.isHidden()
    assert dlg.f_pqv.text() == ""
    dlg.f_pqv.setText(_pqv_key())
    dlg._save()
    assert dlg.result_profile().pqv == _pqv_key()


def test_profile_edit_dialog_refuses_a_malformed_pqv(qapp, warnings):
    p = Profile(name="r", address="a.com", port=443, id="u", network="tcp",
                security="reality", pbk="PUB", sid="ab", sni="a.com")
    dlg = ProfileEditDialog(p)
    dlg.f_pqv.setText("not-a-key")
    dlg._save()
    assert dlg.result_profile().pqv == ""  # nothing was saved
    assert warnings and "ML-DSA-65" in warnings[0]


def test_profile_edit_dialog_hides_pqv_outside_reality(qapp):
    p = Profile(name="t", address="a.com", port=443, id="u", network="tcp", security="tls")
    assert ProfileEditDialog(p).f_pqv.isHidden()


@pytest.mark.parametrize("key,change", [
    ("exits", {"enabled": True, "port": 10809, "password": "pw123456",
               "items": [{"user": "de", "profile_uid": "x"}]}),
    ("forwards", [{"port": 2222, "target": "10.8.0.5:22", "via": "proxy", "network": "tcp"}]),
    ("gateway", {"enabled": False, "start_hotspot": True, "ssid": "Home", "password": "",
                 "security": "wpa3", "band": "auto", "hidden": False, "isolation": False}),
])
def test_settings_that_xray_reads_at_startup_ask_for_a_reconnect(
    window, monkeypatch, key, change,
):
    # These are applied when Xray starts, so changing them while connected must
    # say so instead of looking like nothing happened.
    reconnects: list[str] = []
    monkeypatch.setattr(window, "_needs_reconnect", lambda what: reconnects.append(what))

    class _Dlg:
        updateAvailable = _NoSignal()

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

        def values(self):
            values = {k: copy.deepcopy(window.settings[k]) for k in
                      ("tun_mtu", "log_level", "core", "exits", "forwards", "gateway")}
            values[key] = change
            return values

        def geo_updated(self):
            return False

        def restored(self):
            return False

    import xrayui.ui.main_window as main_window_mod

    monkeypatch.setattr(main_window_mod, "SettingsWindow", _Dlg)
    window._open_settings()

    assert reconnects and reconnects[0].endswith("changed")
    assert window.settings[key] == change

