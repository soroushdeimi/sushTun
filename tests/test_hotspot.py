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


def _stub(monkeypatch, stdout, returncode=0):
    monkeypatch.setattr(hotspot, "IS_WIN", True)
    monkeypatch.setattr(
        hotspot.proc, "powershell",
        lambda *a, **k: types.SimpleNamespace(stdout=stdout, returncode=returncode),
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


def test_enable_succeeds_with_tunnel_and_hotspot(monkeypatch):
    _stub(monkeypatch, WITH_HOTSPOT)
    hotspot.enable(public_name="xray0")  # must not raise


def test_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(hotspot, "IS_WIN", False)
    assert hotspot.list_connections() == []
    with pytest.raises(RuntimeError, match="only implemented on Windows"):
        hotspot.enable()
