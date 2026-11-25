"""Windows firewall backend: netsh argv, group tagging, allow-before-block
ordering, rollback, and idempotency. The real netsh cannot be run here, so a
recording fake captures every argv and simulates the group's rule list.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from xrayui.core import _firewall_windows as win
from xrayui.core._firewall_common import FirewallError

NS = SimpleNamespace


class FakeNetsh:
    """Simulates netsh advfirewall: a group of named rules."""

    def __init__(self):
        self.rules: dict[str, dict] = {}  # name -> spec
        self.calls: list[list[str]] = []
        self.fail_add = None  # a rule name whose add should fail

    @staticmethod
    def _spec(args) -> dict:
        # After "netsh advfirewall firewall <verb> rule" the rest is key=value.
        return dict(t.split("=", 1) for t in args[5:] if "=" in t)

    def run(self, args, **_k):
        self.calls.append(list(args))
        if args[0] != "netsh":
            return NS(returncode=0, stdout="", stderr="")
        if "show" in args:
            names = "\n".join(f"Rule Name: {n}" for n in self.rules)
            return NS(returncode=0, stdout=names, stderr="")
        spec = self._spec(args)
        if "add" in args:
            name = spec.get("name")
            if self.fail_add == name:
                return NS(returncode=1, stdout="", stderr="forced")
            self.rules[name] = spec
            return NS(returncode=0, stdout="", stderr="")
        if "delete" in args:
            self.rules.pop(spec.get("name"), None)
            return NS(returncode=0, stdout="", stderr="")
        return NS(returncode=0, stdout="", stderr="")


@pytest.fixture
def fake(monkeypatch):
    netsh = FakeNetsh()
    monkeypatch.setattr(win.proc, "run", netsh.run)
    monkeypatch.setattr(win, "supported", lambda: True)
    return netsh


# -- rule specs --------------------------------------------------------------
def test_rule_specs_cover_tunnel_servers_loopback():
    specs = win._rule_specs("xray0", ["1.2.3.4", "2001:db8::1"], allow_lan=False)
    names = [s["name"] for s in specs]
    assert names[0] == "sushTun tunnel"
    assert "sushTun server 1.2.3.4" in names
    assert "sushTun server 2001:db8::1" in names
    assert "sushTun loopback" in names
    # No LAN rules when allow_lan is off.
    assert not any("lan" in n for n in names)


def test_rule_specs_add_lan_and_dhcp_when_allowed():
    specs = win._rule_specs("xray0", ["1.2.3.4"], allow_lan=True)
    names = [s["name"] for s in specs]
    assert "sushTun dhcp" in names
    assert "sushTun lan 10.0.0.0/8" in names
    assert "sushTun lan 192.168.0.0/16" in names
    assert "sushTun lan6" in names


def test_allow_argv_carries_group_and_priority():
    argv = win._allow_argv({"name": "sushTun tunnel", "remoteip": "any",
                            "iface": "xray0"})
    assert f"group={win.GROUP}" in argv
    assert f"priority={win._ALLOW_PRIORITY}" in argv
    assert "action=allow" in argv
    assert "iface=xray0" in argv


def test_block_argv_has_lower_priority_than_allows():
    # netsh: lower value = evaluated first, so the block must have a HIGHER
    # number than the allows for the allows to win.
    argv = win._block_argv()
    assert "action=block" in argv
    assert f"priority={win._BLOCK_PRIORITY}" in argv
    assert win._BLOCK_PRIORITY > win._ALLOW_PRIORITY


# -- install -----------------------------------------------------------------
def test_install_adds_allows_then_block(fake):
    win.install("xray0", ["1.2.3.4"], allow_lan=True)
    # Every allow is present, and the block-all rule is present.
    assert win._BLOCK_NAME in fake.rules
    assert "sushTun tunnel" in fake.rules
    assert "sushTun server 1.2.3.4" in fake.rules
    # The block rule was added after every allow rule.
    add_order = [c[5].split("=", 1)[1] for c in fake.calls
                 if "add" in c and c[5].startswith("name=")]
    block_idx = add_order.index(win._BLOCK_NAME)
    assert block_idx == len(add_order) - 1


def test_install_clears_leftover_group_rules_first(fake):
    fake.rules["sushTun stale"] = {"name": "sushTun stale"}
    win.install("xray0", ["1.2.3.4"], allow_lan=False)
    assert "sushTun stale" not in fake.rules
    assert win._BLOCK_NAME in fake.rules


def test_install_rolls_back_when_block_fails(fake):
    fake.fail_add = win._BLOCK_NAME
    with pytest.raises(FirewallError, match="block-all"):
        win.install("xray0", ["1.2.3.4"], allow_lan=False)
    # The allow rules added before the failure were rolled back.
    assert fake.rules == {}


def test_install_rolls_back_when_an_allow_fails(fake):
    fake.fail_add = "sushTun server 1.2.3.4"
    with pytest.raises(FirewallError, match="server 1.2.3.4"):
        win.install("xray0", ["1.2.3.4"], allow_lan=False)
    # The tunnel rule added before the failure was rolled back.
    assert fake.rules == {}


# -- remove ------------------------------------------------------------------
def test_remove_deletes_every_rule_in_group(fake):
    win.install("xray0", ["1.2.3.4"], allow_lan=True)
    assert fake.rules
    assert win.remove() == []
    assert fake.rules == {}


def test_remove_is_idempotent_when_empty(fake):
    assert win.remove() == []
    assert fake.rules == {}


# -- is_active ---------------------------------------------------------------
def test_is_active_requires_the_block_rule(fake):
    assert win.is_active() is False
    win.install("xray0", ["1.2.3.4"], allow_lan=False)
    assert win.is_active() is True
    win.remove()
    assert win.is_active() is False
