"""Windows DNS hijack must report whether the resolver actually moved."""
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("returncode, expected", [(0, True), (1, False)])
def test_dns_hijack_reports_command_failure(win_net, monkeypatch, returncode, expected):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(win_net.proc, "run", run)
    assert win_net.set_dns_loopback("Wi-Fi خانه") is expected
    assert "name=Wi-Fi خانه" in calls[0]
