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
