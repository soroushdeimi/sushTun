"""Gateway-mode logic. Parsing fixtures are real output from an elevated probe."""
import types

import pytest

from xrayui.core import hotspot


def _stub(monkeypatch, stdout, returncode=0):
    """Stub PowerShell (and netsh) so nothing touches the real network."""
    monkeypatch.setattr(hotspot, "IS_WIN", True)
    outputs = list(stdout) if isinstance(stdout, list) else None

    def fake_ps(*a, **k):
        text = outputs.pop(0) if outputs else stdout
        return types.SimpleNamespace(stdout=text, returncode=returncode)

    monkeypatch.setattr(hotspot.proc, "powershell", fake_ps)
    monkeypatch.setattr(
        hotspot.proc, "run",
        lambda *a, **k: types.SimpleNamespace(stdout="", returncode=0),
    )


# -- Windows Mobile Hotspot (WinRT tethering) ------------------------------
# Verbatim from GetCurrentAccessPointConfiguration() on a Windows 11 box.
AP_CONFIG = ('{"ssid":"DESKTOP-1VNQCEE 9299","password":"m98&83Q0",'
             '"band":"Auto","auth":"Wpa2"}')


def test_access_point_configuration_is_parsed(monkeypatch):
    _stub(monkeypatch, AP_CONFIG)
    assert hotspot.tethering_config() == {
        "ssid": "DESKTOP-1VNQCEE 9299", "password": "m98&83Q0",
        "band": "Auto", "auth": "Wpa2"}


def test_unreadable_access_point_configuration_is_none(monkeypatch):
    _stub(monkeypatch, "no-profile", returncode=1)
    assert hotspot.tethering_config() is None


def test_settings_are_translated_into_windows_names(monkeypatch):
    """Settings → Hotspot speaks nmcli's vocabulary; WinRT has its own."""
    seen = {}
    _stub(monkeypatch, "")
    monkeypatch.setattr(
        hotspot.proc, "powershell",
        lambda _s, env=None, **k: (seen.update(env or {}),
                                   types.SimpleNamespace(stdout="", returncode=0))[1])
    assert hotspot.configure_tethering("Phone", "secretpass", security="wpa3", band="a")
    assert seen["AP_SSID"] == "Phone" and seen["AP_PASS"] == "secretpass"
    assert seen["AP_BAND"] == "FiveGigahertz" and seen["AP_AUTH"] == "Wpa3"


def test_blank_and_unknown_choices_keep_what_windows_has(monkeypatch):
    """An empty field means 'leave it alone', and so does a value WinRT
    has no name for -- neither may blank out the hotspot's own settings."""
    seen = {}
    _stub(monkeypatch, "")
    monkeypatch.setattr(
        hotspot.proc, "powershell",
        lambda _s, env=None, **k: (seen.update(env or {}),
                                   types.SimpleNamespace(stdout="", returncode=0))[1])
    hotspot.configure_tethering(band="sixtyghz")
    assert seen["AP_SSID"] == "" and seen["AP_PASS"] == ""
    assert seen["AP_BAND"] == "" and seen["AP_AUTH"] == ""


def _record_ps(monkeypatch, seen):
    monkeypatch.setattr(
        hotspot.proc, "powershell",
        lambda _s, env=None, **k: (seen.append(env),
                                   types.SimpleNamespace(stdout="On", returncode=0))[1])


def test_the_hotspot_is_started_from_the_tunnel_adapter(monkeypatch):
    """Windows shares the connection the hotspot was started from. Legacy ICS
    pointed at the tunnel afterwards fails next to the Mobile Hotspot on
    Windows 11 (0x80040201), so the tunnel has to be the source itself."""
    seen = []
    _stub(monkeypatch, "On")
    _record_ps(monkeypatch, seen)
    assert hotspot.start_tethering("xray0")
    assert hotspot.stop_tethering("xray0")
    assert hotspot.tethering_state("xray0") == "On"
    assert [e["TETHER_ACTION"] for e in seen] == ["start", "stop", "status"]
    assert all(e["TETHER_SOURCE"] == "xray0" for e in seen)


def test_without_a_source_the_internet_connection_is_shared(monkeypatch):
    seen = []
    _stub(monkeypatch, "On")
    _record_ps(monkeypatch, seen)
    hotspot.start_tethering()
    assert seen[0]["TETHER_SOURCE"] == ""


def test_the_tether_script_finds_the_profile_by_adapter_guid():
    """Profile names are made up by Windows ("Network 3", the Wi-Fi SSID);
    the adapter GUID is what ties a profile to xray0. Start waits for it,
    since a new tunnel has no profile until Windows identifies its network."""
    ps = hotspot._TETHER_PS
    assert "NetworkAdapterId" in ps and "InterfaceGuid" in ps
    assert "GetConnectionProfiles" in ps and "no-profile" in ps
    assert "EnableSharing" not in ps


def test_tethering_start_reports_the_state_windows_reached(monkeypatch):
    """The script polls TetheringOperationalState and exits non-zero if it
    never gets there -- reading the async op's .Status always yielded $null
    under Windows PowerShell, so start always claimed to have failed."""
    _stub(monkeypatch, "On")
    assert hotspot.start_tethering()
    _stub(monkeypatch, "Off", returncode=1)
    assert not hotspot.start_tethering()


def test_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(hotspot, "IS_WIN", False)
    assert hotspot.tethering_state() == "unavailable"
    assert hotspot.tethering_config() is None
    assert not hotspot.configure_tethering("Phone", "secretpass")


def test_disable_leaves_windows_sharing_alone(monkeypatch):
    """It used to clear every ICS share on the machine, the user's own too."""
    _stub(monkeypatch, "")
    monkeypatch.setattr(hotspot, "IS_LINUX", False)
    ran = []
    monkeypatch.setattr(hotspot.proc, "powershell", lambda *a, **k: ran.append(a))
    hotspot.disable()
    assert ran == []


# -- Linux (NetworkManager) ------------------------------------------------
# Verbatim from the development laptop: an Intel card, connected as a client.
IW_DEV_INFO = (
    "Interface wlp2s0\n\tifindex 2\n\twdev 0x1\n\taddr 90:e8:68:d1:8d:8d\n"
    "\ttype managed\n\twiphy 0\n"
    "\tchannel 6 (2437 MHz), width: 20 MHz, center1: 2437 MHz\n\ttxpower 3.00 dBm\n"
)
_MODES = "Wiphy phy0\n\tSupported interface modes:\n\t\t * managed\n\t\t * AP\n"
_COMBO_P2P = ("\t\t * #{ managed, P2P-client } <= 2, #{ P2P-GO } <= 1, #{ P2P-device } <= 1,\n"
              "\t\t   total <= 3, #channels <= 2\n")
_COMBO_AP = ("\t\t * #{ managed, P2P-client } <= 2, #{ AP } <= 1, #{ P2P-device } <= 1,\n"
             "\t\t   total <= 3, #channels <= 1\n")
_TAIL = "\tHT Capability overrides:\n\t\t * MCS: ff ff ff ff\n"
IW_PHY = _MODES + "\tvalid interface combinations:\n" + _COMBO_P2P + _COMBO_AP + _TAIL
# The radio can be an AP, just never beside a client: modes list AP, no combo does.
IW_PHY_NO_CONCURRENT_AP = _MODES + "\tvalid interface combinations:\n" + _COMBO_P2P + _TAIL
NM_STATUS = ("{wifi}\nlo:loopback:connected (externally)\n"
             "xray0:tun:connected (externally)\np2p-dev-wlp2s0:wifi-p2p:disconnected\n")


def _linux(monkeypatch, *, wifi_state="connected", phy=IW_PHY, up_rc=0):
    """Stub nmcli/iw; a virtual interface 'exists' once `iw ... interface add` runs."""
    monkeypatch.setattr(hotspot, "IS_WIN", False)
    monkeypatch.setattr(hotspot, "IS_LINUX", True)
    monkeypatch.setattr(hotspot.time, "sleep", lambda _s: None)
    monkeypatch.setattr(hotspot, "_local_mac", lambda dev: "92:e8:68:d1:8d:8d")
    ran: list[list[str]] = []
    vif = {"exists": False}

    def run(args, **_k):
        args = list(args)
        ran.append(args)
        rc, out = 0, ""
        if args[:4] == ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE"]:
            out = NM_STATUS.format(wifi=f"wlp2s0:wifi:{wifi_state}")
        elif args[:4] == ["nmcli", "-t", "-f", "DEVICE,STATE"]:
            out = "wlp2s0:connected\n" + ("sushap0:disconnected\n" if vif["exists"] else "")
        elif args == ["iw", "dev", "wlp2s0", "info"]:
            out = IW_DEV_INFO
        elif args[:2] == ["iw", "phy"]:
            out = phy
        elif args == ["iw", "dev", hotspot.AP_IFACE, "info"]:
            rc = 0 if vif["exists"] else 1
        elif args[:5] == ["iw", "dev", "wlp2s0", "interface", "add"]:
            vif["exists"] = True
        elif args == ["iw", "dev", hotspot.AP_IFACE, "del"]:
            vif["exists"] = False
        elif args[:3] == ["nmcli", "connection", "up"]:
            rc = up_rc
        return types.SimpleNamespace(returncode=rc, stdout=out,
                                     stderr="Error: Connection activation failed." if rc else "")

    monkeypatch.setattr(hotspot.proc, "run", run)
    # Never touch the real /proc/sys from a test; record the change instead.
    monkeypatch.setattr(hotspot, "_set_forwarding",
                        lambda iface, on: ran.append(["forwarding", iface, "1" if on else "0"]))
    return ran, vif


def _profile(ran):
    return next(c for c in ran if c[:3] == ["nmcli", "connection", "add"])


def test_radio_that_allows_ap_beside_a_client_is_recognised(monkeypatch):
    _linux(monkeypatch)
    assert hotspot._can_ap_while_connected(0)
    _linux(monkeypatch, phy=IW_PHY_NO_CONCURRENT_AP)
    assert not hotspot._can_ap_while_connected(0)


def test_client_channel_is_read_from_iw(monkeypatch):
    _linux(monkeypatch)
    assert hotspot._iw_info("wlp2s0") == (0, 6, 2437)


def test_connected_card_gets_a_virtual_hotspot_on_its_own_channel(monkeypatch):
    ran, vif = _linux(monkeypatch)

    assert hotspot.start_linux("sushTun", "secretpass") == hotspot.AP_IFACE
    # The client link (the internet) stays up: the AP is a second interface.
    assert ["iw", "dev", "wlp2s0", "interface", "add", hotspot.AP_IFACE, "type", "__ap",
            "addr", "92:e8:68:d1:8d:8d"] in ran
    profile = _profile(ran)
    assert profile[profile.index("ifname") + 1] == hotspot.AP_IFACE
    assert profile[profile.index("802-11-wireless.channel") + 1] == "6"
    assert profile[profile.index("802-11-wireless.band") + 1] == "bg"
    assert profile[profile.index("ipv4.method") + 1] == "shared"
    # The tunnel is IPv4-only: shared IPv6 would give clients a way around it.
    assert profile[profile.index("ipv6.method") + 1] == "disabled"


def test_radio_without_concurrent_ap_is_refused_before_touching_the_wifi(monkeypatch):
    ran, _vif = _linux(monkeypatch, phy=IW_PHY_NO_CONCURRENT_AP)
    with pytest.raises(RuntimeError, match="cannot run a hotspot while it is connected"):
        hotspot.start_linux("sushTun", "secretpass")
    assert not any(c[:5] == ["iw", "dev", "wlp2s0", "interface", "add"] for c in ran)
    assert not any(c[:3] == ["nmcli", "connection", "add"] for c in ran)


def test_idle_card_hosts_the_hotspot_itself(monkeypatch):
    ran, _vif = _linux(monkeypatch, wifi_state="disconnected")
    assert hotspot.start_linux("sushTun", "secretpass") == "wlp2s0"
    assert not any(c[:5] == ["iw", "dev", "wlp2s0", "interface", "add"] for c in ran)
    assert "802-11-wireless.channel" not in _profile(ran)


def test_failed_start_leaves_nothing_behind(monkeypatch):
    ran, vif = _linux(monkeypatch, up_rc=4)
    with pytest.raises(RuntimeError, match="did not start: Error: Connection activation failed"):
        hotspot.start_linux("sushTun", "secretpass")
    up = ran.index(["nmcli", "connection", "up", hotspot.AP_CON])
    assert ["nmcli", "connection", "delete", hotspot.AP_CON] in ran[up:]
    assert not vif["exists"]


def test_disable_takes_the_linux_hotspot_down(monkeypatch):
    ran, vif = _linux(monkeypatch)
    vif["exists"] = True
    hotspot.disable()
    assert ["nmcli", "connection", "down", hotspot.AP_CON] in ran
    assert ["nmcli", "connection", "delete", hotspot.AP_CON] in ran
    assert not vif["exists"]


def test_hotspot_password_is_made_once_and_kept(monkeypatch, tmp_path):
    from xrayui import paths
    from xrayui.core import connection
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)

    ssid, first = connection._hotspot_credentials()
    assert ssid == "sushTun" and 8 <= len(first) <= 63
    assert connection._hotspot_credentials() == (ssid, first)  # phones rejoin by themselves


def test_linux_connect_starts_the_hotspot_and_says_how_to_join(monkeypatch, tmp_path):
    from xrayui import paths
    from xrayui.core import connection
    from xrayui.core import settings as app_settings
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    settings = app_settings.load()
    settings["gateway"].update(enabled=True, password="joinme123")
    app_settings.save(settings)
    monkeypatch.setattr(connection, "IS_WIN", False)
    monkeypatch.setattr(connection.hotspot, "supported", lambda: True)
    monkeypatch.setattr(connection.hotspot, "start_linux",
                        lambda ssid, pw, **kw: hotspot.AP_IFACE)

    steps = []
    conn = connection.Connection(on_step=steps.append)
    conn._setup_gateway()

    assert any('"sushTun" is on' in s and "joinme123" in s for s in steps)
    assert conn.state.gateway_on()


def test_disconnect_drops_the_hotspot_before_the_tunnel(monkeypatch, tmp_path):
    # Left up after the tunnel, clients would be NATed out of the physical
    # link unprotected, so the hotspot must go first.
    from xrayui import paths
    from xrayui.core import connection
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "cfg.json")
    monkeypatch.setattr(connection, "IS_WIN", False)
    order = []
    monkeypatch.setattr(connection.hotspot, "disable", lambda: order.append("hotspot"))
    monkeypatch.setattr(connection.network, "remove_routes", lambda ip=None: None)
    monkeypatch.setattr(connection.network, "restore_dns", lambda *a, **k: True)
    monkeypatch.setattr(connection.network, "release_stranded_dns", lambda exclude=None: [])
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: None)

    conn = connection.Connection()
    conn._gateway_on = True
    conn.xray.stop = lambda: order.append("xray")
    conn.tun2socks.stop = lambda: None
    conn._restore()

    assert order.index("hotspot") < order.index("xray")


def test_hotspot_turns_on_forwarding_for_replies_from_the_tunnel(monkeypatch):
    ran, _vif = _linux(monkeypatch)
    hotspot.start_linux("sushTun", "secretpass")
    up = ran.index(["nmcli", "connection", "up", hotspot.AP_CON])
    assert ["forwarding", hotspot.TUN_NAME, "1"] in ran[up:]


def test_failed_hotspot_leaves_forwarding_alone(monkeypatch):
    ran, _vif = _linux(monkeypatch, up_rc=4)
    with pytest.raises(RuntimeError):
        hotspot.start_linux("sushTun", "secretpass")
    assert ["forwarding", hotspot.TUN_NAME, "1"] not in ran


def test_stopping_the_hotspot_turns_tunnel_forwarding_off_first(monkeypatch):
    ran, vif = _linux(monkeypatch)
    vif["exists"] = True
    hotspot.stop_linux()
    assert ran[0] == ["forwarding", hotspot.TUN_NAME, "0"]


def test_set_forwarding_writes_the_per_interface_switch(monkeypatch, tmp_path):
    target = tmp_path / "xray0"
    monkeypatch.setattr(hotspot, "_FORWARDING", str(tmp_path / "{}"))
    hotspot._set_forwarding("xray0", True)
    assert target.read_text() == "1"
    hotspot._set_forwarding("xray0", False)
    assert target.read_text() == "0"


def test_set_forwarding_never_raises_without_permission(monkeypatch, tmp_path):
    monkeypatch.setattr(hotspot, "_FORWARDING", str(tmp_path / "missing" / "{}"))
    hotspot._set_forwarding("xray0", True)


def _gateway_conn(monkeypatch, tmp_path):
    from xrayui import paths
    from xrayui.core import connection
    from xrayui.core import settings as app_settings
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    settings = app_settings.load()
    settings["gateway"].update(enabled=True, password="joinme123")
    app_settings.save(settings)
    monkeypatch.setattr(connection, "IS_WIN", False)
    monkeypatch.setattr(connection.hotspot, "supported", lambda: True)
    return connection.Connection()


def test_start_gateway_refuses_before_connecting(monkeypatch, tmp_path):
    conn = _gateway_conn(monkeypatch, tmp_path)
    started = []
    monkeypatch.setattr(conn.state, "is_connected", lambda: False)
    monkeypatch.setattr("xrayui.core.connection.hotspot.start_linux",
                        lambda ssid, pw, **kw: started.append(ssid))
    with pytest.raises(RuntimeError, match="connect first"):
        conn.start_gateway()
    assert started == []


def test_start_gateway_shares_an_existing_connection_and_reports_failure(monkeypatch, tmp_path):
    conn = _gateway_conn(monkeypatch, tmp_path)
    monkeypatch.setattr(conn.state, "is_connected", lambda: True)
    monkeypatch.setattr("xrayui.core.connection.hotspot.start_linux",
                        lambda ssid, pw, **kw: hotspot.AP_IFACE)
    conn.start_gateway()
    assert conn.state.gateway_on()

    def refuse(ssid, pw, **kw):
        raise RuntimeError("hotspot did not start")

    monkeypatch.setattr("xrayui.core.connection.hotspot.start_linux", refuse)
    with pytest.raises(RuntimeError, match="did not start"):
        conn.start_gateway()


def test_hotspot_offers_wpa2_with_aes_only(monkeypatch):
    ran, _vif = _linux(monkeypatch)
    hotspot.start_linux("sushTun", "secretpass")
    profile = _profile(ran)
    # Without these, phones warn "weak security" (WPA1/TKIP were on offer).
    assert profile[profile.index("wifi-sec.proto") + 1] == "rsn"
    assert profile[profile.index("wifi-sec.pairwise") + 1] == "ccmp"
    assert profile[profile.index("wifi-sec.group") + 1] == "ccmp"


# -- Settings → Hotspot options ---------------------------------------------------
# Today's exact command for an idle card. The options below must leave it alone
# while they are at their defaults.
_TODAY = ["nmcli", "connection", "add", "type", "wifi", "ifname", "wlp2s0",
          "con-name", "sushTun Hotspot", "autoconnect", "no", "ssid", "sushTun",
          "802-11-wireless.mode", "ap", "ipv4.method", "shared", "ipv6.method", "disabled",
          "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.proto", "rsn",
          "wifi-sec.pairwise", "ccmp", "wifi-sec.group", "ccmp", "wifi-sec.psk", "secretpass"]


def test_default_options_give_exactly_todays_hotspot(monkeypatch):
    ran, _vif = _linux(monkeypatch, wifi_state="disconnected")
    hotspot.start_linux("sushTun", "secretpass")
    assert _profile(ran) == _TODAY


def test_unknown_option_values_fall_back_to_todays_hotspot(monkeypatch):
    ran, _vif = _linux(monkeypatch, wifi_state="disconnected")
    hotspot.start_linux("sushTun", "secretpass", security="wep", band_choice="60GHz")
    assert _profile(ran) == _TODAY


def test_wpa3_uses_sae_with_required_management_frame_protection(monkeypatch):
    ran, _vif = _linux(monkeypatch, wifi_state="disconnected")
    hotspot.start_linux("sushTun", "secretpass", security="wpa3")
    profile = _profile(ran)
    assert profile[profile.index("wifi-sec.key-mgmt") + 1] == "sae"
    assert profile[profile.index("wifi-sec.pmf") + 1] == "required"


def test_hidden_and_isolation_are_added_only_when_asked(monkeypatch):
    ran, _vif = _linux(monkeypatch, wifi_state="disconnected")
    hotspot.start_linux("sushTun", "secretpass", hidden=True, isolation=True)
    profile = _profile(ran)
    assert profile[profile.index("802-11-wireless.hidden") + 1] == "yes"
    assert profile[profile.index("802-11-wireless.ap-isolation") + 1] == "1"


def test_band_choice_applies_on_an_idle_card(monkeypatch):
    ran, _vif = _linux(monkeypatch, wifi_state="disconnected")
    hotspot.start_linux("sushTun", "secretpass", band_choice="a")
    profile = _profile(ran)
    assert profile[profile.index("802-11-wireless.band") + 1] == "a"
    assert "802-11-wireless.channel" not in profile  # NetworkManager picks it


def test_band_choice_yields_to_the_uplink_on_a_shared_radio(monkeypatch):
    ran, _vif = _linux(monkeypatch)  # connected on 2.4 GHz channel 6
    hotspot.start_linux("sushTun", "secretpass", band_choice="a")
    profile = _profile(ran)
    assert profile[profile.index("802-11-wireless.band") + 1] == "bg"
    assert profile.count("802-11-wireless.band") == 1


def test_start_gateway_passes_the_hotspot_options(monkeypatch, tmp_path):
    from xrayui.core import settings as app_settings
    conn = _gateway_conn(monkeypatch, tmp_path)
    settings = app_settings.load()
    settings["gateway"].update(security="wpa3", band="a", hidden=True, isolation=True)
    app_settings.save(settings)
    monkeypatch.setattr(conn.state, "is_connected", lambda: True)
    seen = {}
    monkeypatch.setattr("xrayui.core.connection.hotspot.start_linux",
                        lambda ssid, pw, **kw: (seen.update(kw), hotspot.AP_IFACE)[1])
    conn.start_gateway()
    assert seen == {"security": "wpa3", "band_choice": "a", "hidden": True, "isolation": True}


# -- Windows: Settings → Hotspot reaches Windows only when the user asked ---------------
def test_windows_hotspot_is_left_alone_until_the_user_edits_it(monkeypatch, tmp_path):
    from xrayui.core import connection
    conn = _gateway_conn(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(connection.hotspot, "configure_tethering",
                        lambda *a, **k: calls.append((a, k)) or True)
    conn._configure_windows_hotspot({"ssid": "sushTun", "password": "", "security": "wpa2",
                                     "band": "auto", "apply_on_windows": False})
    assert calls == []


def test_a_windows_edit_is_applied_once(monkeypatch, tmp_path):
    from xrayui.core import connection
    from xrayui.core import settings as app_settings
    conn = _gateway_conn(monkeypatch, tmp_path)
    settings = app_settings.load()
    settings["gateway"].update(ssid="Home AP", apply_on_windows=True)
    app_settings.save(settings)
    calls = []
    monkeypatch.setattr(connection.hotspot, "configure_tethering",
                        lambda *a, **k: calls.append((a, k)) or True)
    conn._configure_windows_hotspot(app_settings.load()["gateway"])
    conn._configure_windows_hotspot(app_settings.load()["gateway"])
    assert len(calls) == 1 and calls[0][0][0] == "Home AP"
    assert app_settings.load()["gateway"]["apply_on_windows"] is False  # applied once



def test_failed_windows_apply_keeps_the_edit_pending(monkeypatch, tmp_path):
    from xrayui.core import connection
    from xrayui.core import settings as app_settings
    conn = _gateway_conn(monkeypatch, tmp_path)
    settings = app_settings.load()
    settings["gateway"].update(ssid="Retry name", apply_on_windows=True)
    app_settings.save(settings)
    monkeypatch.setattr(connection.hotspot, "configure_tethering", lambda *a, **k: False)
    conn._configure_windows_hotspot(app_settings.load()["gateway"])
    assert app_settings.load()["gateway"]["apply_on_windows"] is True


# -- Windows: the hotspot runs on the tunnel, and only sushTun's doing is undone --
# Windows shares whichever connection the Mobile Hotspot was started from.
# sushTun starts it from the tunnel; a hotspot the user already had running
# (on Wi-Fi) is moved onto the tunnel and handed back to Wi-Fi afterwards.
class _FakeHotspot:
    """One Mobile Hotspot per machine, as on Windows."""

    def __init__(self, on=False, source="Wi-Fi", start_ok=True):
        self.on, self.source, self.start_ok = on, source, start_ok
        self.calls = []

    def state(self, source=""):
        return "On" if self.on else "Off"

    def start(self, source=""):
        self.calls.append(("start", source))
        if self.start_ok or source != "xray0":
            self.on, self.source = True, source
            return True
        return False

    def stop(self, source=""):
        self.calls.append(("stop", source))
        self.on = False
        return True


def _win_gateway(monkeypatch, tmp_path, **hs):
    from xrayui import paths
    from xrayui.core import connection
    from xrayui.core.network import DnsState, Interface
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "cfg.json")
    monkeypatch.setattr(connection, "IS_WIN", True)
    monkeypatch.setattr(connection.network, "TUN_NAME", "xray0")
    fake = _FakeHotspot(**hs)
    monkeypatch.setattr(connection.hotspot, "tethering_state", fake.state)
    monkeypatch.setattr(connection.hotspot, "start_tethering", fake.start)
    monkeypatch.setattr(connection.hotspot, "stop_tethering", fake.stop)
    monkeypatch.setattr(connection.hotspot, "disable",
                        lambda: pytest.fail("Windows must not touch ICS"))
    conn = connection.Connection()
    conn.state.save(Interface("Wi-Fi", "192.168.1.50", "192.168.1.1", 12),
                    "203.0.113.10", 23, DnsState(mode="DHCP", servers=[]))
    return conn, fake


def _restore_stubs(monkeypatch):
    from xrayui.core import connection
    monkeypatch.setattr(connection.network, "remove_routes", lambda ip=None: None)
    monkeypatch.setattr(connection.network, "restore_dns", lambda *a, **k: True)
    monkeypatch.setattr(connection.network, "release_stranded_dns", lambda exclude=None: [])
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: None)


def test_a_hotspot_that_was_off_is_started_on_the_tunnel(monkeypatch, tmp_path):
    conn, fake = _win_gateway(monkeypatch, tmp_path)
    conn._start_gateway({})
    assert fake.calls == [("start", "xray0")]
    assert (fake.on, fake.source) == (True, "xray0")
    assert conn.state.tethering() == "started"


def test_switching_off_stops_the_hotspot_sushtun_started(monkeypatch, tmp_path):
    conn, fake = _win_gateway(monkeypatch, tmp_path)
    conn._start_gateway({})
    conn.stop_gateway()
    assert fake.calls[1:] == [("stop", "xray0")]
    assert not fake.on and conn.state.tethering() == ""


def test_the_users_running_hotspot_is_moved_onto_the_tunnel(monkeypatch, tmp_path):
    """Left on Wi-Fi, its devices bypassed the tunnel entirely."""
    conn, fake = _win_gateway(monkeypatch, tmp_path, on=True)
    conn._start_gateway({})
    assert fake.calls == [("stop", ""), ("start", "xray0")]
    assert conn.state.tethering() == "moved"


def test_the_users_hotspot_goes_back_to_wifi_when_sharing_ends(monkeypatch, tmp_path):
    conn, fake = _win_gateway(monkeypatch, tmp_path, on=True)
    conn._start_gateway({})
    conn.stop_gateway()
    assert fake.calls[2:] == [("stop", "xray0"), ("start", "Wi-Fi")]
    assert (fake.on, fake.source) == (True, "Wi-Fi")


def test_a_refused_start_gives_the_user_their_hotspot_back(monkeypatch, tmp_path):
    conn, fake = _win_gateway(monkeypatch, tmp_path, on=True, start_ok=False)
    with pytest.raises(RuntimeError, match="on the tunnel"):
        conn._start_gateway({})
    assert fake.calls[-1] == ("start", "Wi-Fi") and fake.on
    assert conn.state.tethering() == ""


def test_a_refused_start_leaves_an_off_hotspot_off(monkeypatch, tmp_path):
    conn, fake = _win_gateway(monkeypatch, tmp_path, start_ok=False)
    with pytest.raises(RuntimeError):
        conn._start_gateway({})
    assert not fake.on and conn.state.tethering() == ""


def test_start_hotspot_off_needs_the_hotspot_already_running(monkeypatch, tmp_path):
    conn, fake = _win_gateway(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="turn it on first"):
        conn._start_gateway({"start_hotspot": False})
    assert fake.calls == []


def test_starting_twice_does_not_restart_a_hotspot_already_on_the_tunnel(monkeypatch, tmp_path):
    conn, fake = _win_gateway(monkeypatch, tmp_path)
    conn._start_gateway({})
    conn._start_gateway({})
    assert fake.calls == [("start", "xray0")]


def test_after_an_app_restart_the_switch_still_turns_sharing_off(monkeypatch, tmp_path):
    """What sushTun did lived only in memory: a restarted app's switch did
    nothing and the hotspot kept sharing."""
    from xrayui.core import connection
    first, fake = _win_gateway(monkeypatch, tmp_path)
    first._start_gateway({})
    second = connection.Connection()
    second.stop_gateway()
    assert fake.calls[-1] == ("stop", "xray0") and not fake.on
    assert not second.state.gateway_on()


def test_crash_recovery_hands_the_users_hotspot_back(monkeypatch, tmp_path):
    from xrayui.core import connection
    _restore_stubs(monkeypatch)
    first, fake = _win_gateway(monkeypatch, tmp_path, on=True)
    first._start_gateway({})
    order = []
    second = connection.Connection()
    second.xray.stop = lambda: order.append(list(fake.calls))
    second._restore()
    assert order[0][-2:] == [("stop", "xray0"), ("start", "Wi-Fi")]  # before Xray stops
    assert (fake.on, fake.source) == (True, "Wi-Fi")


def test_disconnecting_stops_the_hotspot_before_the_tunnel(monkeypatch, tmp_path):
    _restore_stubs(monkeypatch)
    conn, fake = _win_gateway(monkeypatch, tmp_path)
    conn._start_gateway({})
    seen = []
    conn.xray.stop = lambda: seen.append(fake.on)
    conn._restore()
    assert seen == [False]


def test_a_hotspot_sushtun_did_not_touch_is_left_alone(monkeypatch, tmp_path):
    conn, fake = _win_gateway(monkeypatch, tmp_path, on=True)
    conn.state.set_gateway(True)  # e.g. sharing from an older version
    conn.stop_gateway()
    assert fake.calls == [] and fake.on


def test_windows_settings_are_not_pushed_again_after_the_window_saves(monkeypatch, tmp_path):
    """The window saves its own copy of the settings, which still says the
    edit is pending, so the same name and password went to Windows on every
    connect."""
    from xrayui.core import connection
    from xrayui.core import settings as app_settings
    conn = _gateway_conn(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(connection.hotspot, "configure_tethering",
                        lambda *a, **k: calls.append(a) or True)
    stale = {"ssid": "Home AP", "password": "secretpass", "security": "wpa2",
             "band": "auto", "apply_on_windows": True}
    conn._configure_windows_hotspot(stale)
    settings = app_settings.load()
    settings["gateway"].update(stale)  # the window's save
    app_settings.save(settings)
    conn._configure_windows_hotspot(app_settings.load()["gateway"])
    assert len(calls) == 1
    conn._configure_windows_hotspot({**stale, "password": "newsecret1"})
    assert len(calls) == 2  # a real new edit still goes through
