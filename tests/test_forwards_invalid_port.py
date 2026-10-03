"""Malformed optional forward ports must not interrupt the main connection."""
import pytest

from xrayui.core import forwards


@pytest.mark.parametrize("port", ["²", "9" * 5000])
def test_unparseable_target_port_is_skipped_with_warning(monkeypatch, port):
    monkeypatch.setattr(forwards.exits, "port_is_free", lambda port: True)
    items = [
        {"port": 12000, "target": f"example.com:{port}", "via": "proxy"},
        {"port": 12001, "target": "[2001:db8::1]:443", "via": "direct"},
    ]
    kept, warnings = forwards.prepare(items, {}, {})
    assert len(warnings) == 1
    assert "skipped" in warnings[0]
    assert [(f.port, f.host, f.target_port) for f in kept] == [(12001, "2001:db8::1", 443)]
