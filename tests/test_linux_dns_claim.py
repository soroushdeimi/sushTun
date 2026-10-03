"""DNS ownership checks with all system commands mocked."""
from types import SimpleNamespace

import pytest

from xrayui.core import _net_posix as posix


@pytest.mark.parametrize("domain,code", [("", 0), ("example.org", 0), ("~.", 1)])
def test_dns_claim_requires_the_routing_domain(monkeypatch, domain, code):
    monkeypatch.setattr(posix, "IS_MAC", False)
    monkeypatch.setattr(posix, "_resolved_active", lambda: True)
    monkeypatch.setattr(posix.shutil, "which", lambda name: None)
    monkeypatch.setattr(posix.time, "sleep", lambda seconds: None)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        output = ""
        rc = 0
        if args == ["resolvectl", "dns", posix.TUN_NAME]:
            output = f"Link 10 (xray0): {posix.TUN_DNS}\n"
        if args == ["resolvectl", "domain", posix.TUN_NAME]:
            output, rc = f"Link 10 (xray0): {domain}\n", code
        return SimpleNamespace(stdout=output, stderr="", returncode=rc)

    monkeypatch.setattr(posix.proc, "run", run)
    assert posix.set_dns_loopback("wlp2s0.100") is False
    assert calls.count(["resolvectl", "domain", "xray0", "~."]) == 5


def test_dns_watchdog_repairs_a_cleared_domain_with_server_intact(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", False)
    monkeypatch.setattr(posix, "_resolved_active", lambda: True)
    monkeypatch.setattr(posix.shutil, "which", lambda name: None)
    monkeypatch.setattr(posix.time, "sleep", lambda seconds: None)
    domains = []

    def run(args, **kwargs):
        output = ""
        if args == ["resolvectl", "dns", posix.TUN_NAME]:
            output = f"Link 10 (xray0): {posix.TUN_DNS}\n"
        if args == ["resolvectl", "domain", posix.TUN_NAME, "~."]:
            domains.append("~.")
        if args == ["resolvectl", "domain", posix.TUN_NAME]:
            output = "Link 10 (xray0): " + " ".join(domains)
        return SimpleNamespace(stdout=output, stderr="", returncode=0)

    monkeypatch.setattr(posix.proc, "run", run)
    assert posix.repair_tun_dns() is True
    assert domains == ["~."]
