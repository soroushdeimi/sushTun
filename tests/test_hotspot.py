"""Gateway-mode logic. Parsing fixtures are real output from an elevated probe."""
import types

import pytest

from xrayui.core import hotspot

# Verbatim from `HNetCfg.HNetShare` on a Windows box with the tunnel up.
REAL_OUTPUT = (
    '[{"name":"vEthernet (Default Switch)","status":2,"shared":false,"role":0},'
    '{"name":"Bluetooth Network Connection","status":7,"shared":false,"role":0},'
    '{"name":"xray0","status":2,"shared":false,"role":0},'
    '{"name":"Ethernet","status":7,"shared":false,"role":0},'
    '{"name":"Wi-Fi","status":2,"shared":false,"role":0}]'
)

WITH_HOTSPOT = (
    '[{"name":"xray0","status":2,"shared":false,"role":0},'
    '{"name":"Local Area Connection* 3","status":2,"shared":false,"role":0}]'
)


SHARED_OK = (
    '[{"name":"xray0","status":2,"shared":true,"role":0},'
    '{"name":"Local Area Connection* 3","status":2,"shared":true,"role":1}]'
)


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


def test_parses_real_connection_list(monkeypatch):
    _stub(monkeypatch, REAL_OUTPUT)
    names = [c.name for c in hotspot.list_connections()]
    assert "xray0" in names and "Wi-Fi" in names
    tunnel = next(c for c in hotspot.list_connections() if c.name == "xray0")
    assert tunnel.connected and not tunnel.shared


def test_disconnected_adapters_are_not_connected(monkeypatch):
    _stub(monkeypatch, REAL_OUTPUT)
    eth = next(c for c in hotspot.list_connections() if c.name == "Ethernet")
    assert not eth.connected  # status 7 = disconnected


def test_hotspot_adapter_detected_only_when_present(monkeypatch):
    _stub(monkeypatch, REAL_OUTPUT)
    assert hotspot.find_hotspot_adapter() is None
    _stub(monkeypatch, WITH_HOTSPOT)
    assert hotspot.find_hotspot_adapter() == "Local Area Connection* 3"


def test_enable_refuses_without_a_hotspot(monkeypatch):
    _stub(monkeypatch, REAL_OUTPUT)
    with pytest.raises(RuntimeError, match="hotspot"):
        hotspot.enable()


def test_enable_refuses_when_tunnel_is_missing(monkeypatch):
    _stub(monkeypatch, '[{"name":"Local Area Connection* 3","status":2,'
                       '"shared":false,"role":0}]')
    with pytest.raises(RuntimeError, match="not found"):
        hotspot.enable(public_name="xray0")


def test_enable_reports_failure_from_powershell(monkeypatch):
    _stub(monkeypatch, WITH_HOTSPOT, returncode=1)
    with pytest.raises(RuntimeError, match="failed to enable"):
        hotspot.enable(public_name="xray0")


def test_enable_succeeds_once_windows_reports_sharing(monkeypatch):
    # pre-check list, the set call, then the post-check list showing it applied
    _stub(monkeypatch, [WITH_HOTSPOT, "", SHARED_OK])
    hotspot.enable(public_name="xray0")  # must not raise


def test_enable_detects_silently_ignored_sharing(monkeypatch):
    # Windows accepts the calls but sharing never turns on (link-local public side)
    _stub(monkeypatch, [WITH_HOTSPOT, "", WITH_HOTSPOT])
    with pytest.raises(RuntimeError, match="did not accept"):
        hotspot.enable(public_name="xray0")


def test_tunnel_gets_a_resolver_before_sharing(monkeypatch):
    """ICS answers client DNS from the shared adapter, which starts with none."""
    calls = []
    _stub(monkeypatch, [WITH_HOTSPOT, "", SHARED_OK])
    monkeypatch.setattr(
        hotspot.proc, "run",
        lambda args, **k: (calls.append(args), types.SimpleNamespace(returncode=0))[1],
    )
    hotspot.enable(public_name="xray0")
    assert any("dnsservers" in " ".join(c) and "127.0.0.1" in " ".join(c) for c in calls)


def test_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(hotspot, "IS_WIN", False)
    assert hotspot.list_connections() == []
    with pytest.raises(RuntimeError, match="only implemented on Windows"):
        hotspot.enable()


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
    monkeypatch.setattr(connection.hotspot, "start_linux", lambda ssid, pw: hotspot.AP_IFACE)

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
