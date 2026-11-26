"""Windows firewall backend. Windows Firewall cannot express "block all except"
(block rules beat allow rules; `netsh` rejects group=, priority= and iface=,
checked on a real Windows), so the backend installs two block rules over the
complement of what must stay reachable. These tests pin the rule contents, the
rollback and the idempotency with a fake netsh.
"""
from __future__ import annotations

import ipaddress
from types import SimpleNamespace

import pytest

from xrayui.core import _firewall_windows as win
from xrayui.core._firewall_common import FirewallError, complement_ranges

NS = SimpleNamespace


class FakeNetsh:
    def __init__(self):
        self.rules: dict[str, dict] = {}
        self.calls: list[list[str]] = []
        self.fail_add = None

    @staticmethod
    def _spec(args) -> dict:
        return dict(t.split("=", 1) for t in args[5:] if "=" in t)

    def run(self, args, **_k):
        self.calls.append(list(args))
        spec = self._spec(args)
        name = spec.get("name")
        if "show" in args:
            if name in self.rules:
                return NS(returncode=0, stdout=f"Rule Name: {name}\n", stderr="")
            return NS(returncode=1, stdout="No rules match the specified criteria.", stderr="")
        if "add" in args:
            if self.fail_add == name:
                return NS(returncode=1, stdout="The parameter is incorrect.", stderr="")
            self.rules[name] = spec
            return NS(returncode=0, stdout="Ok.", stderr="")
        if "delete" in args:
            found = self.rules.pop(name, None) is not None
            return NS(returncode=0 if found else 1, stdout="", stderr="")
        return NS(returncode=0, stdout="", stderr="")


@pytest.fixture
def fake(monkeypatch):
    netsh = FakeNetsh()
    monkeypatch.setattr(win.proc, "run", netsh.run)
    monkeypatch.setattr(win, "supported", lambda: True)
    return netsh


def _covers(ranges: list[str], ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    for r in ranges:
        lo, _, hi = r.partition("-")
        if ipaddress.ip_address(lo) <= addr <= ipaddress.ip_address(hi or lo):
            return True
    return False


# -- complement_ranges -------------------------------------------------------
def test_complement_of_nothing_is_the_whole_space():
    assert complement_ranges([], 4) == ["0.0.0.0-255.255.255.255"]
    assert complement_ranges([], 6) == ["::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"]


def test_complement_excludes_exactly_the_given_networks():
    r = complement_ranges(["10.0.0.0/8", "1.2.3.4/32"], 4)
    assert not _covers(r, "10.1.2.3") and not _covers(r, "1.2.3.4")
    for ip in ("1.2.3.3", "1.2.3.5", "9.255.255.255", "11.0.0.0", "0.0.0.0",
               "255.255.255.255"):
        assert _covers(r, ip), ip


def test_complement_merges_overlapping_and_adjacent_networks():
    # 10/8 contains 10.1/16; 192.168.0.0/17 and 192.168.128.0/17 are adjacent.
    r = complement_ranges(["10.0.0.0/8", "10.1.0.0/16", "192.168.0.0/17",
                           "192.168.128.0/17"], 4)
    assert len(r) == 3
    assert not _covers(r, "192.168.200.1") and _covers(r, "192.169.0.0")


def test_complement_ignores_the_other_family():
    assert complement_ranges(["2001:db8::/32"], 4) == ["0.0.0.0-255.255.255.255"]


# -- rules -------------------------------------------------------------------
def _rules(allow_lan, ips=("1.2.3.4", "2001:db8::1")):
    v4, v6 = win._rule_argvs("xray0", list(ips), allow_lan)
    return (dict(t.split("=", 1) for t in v4[5:] if "=" in t),
            dict(t.split("=", 1) for t in v6[5:] if "=" in t))


def test_rules_only_use_arguments_netsh_accepts():
    for argv in win._rule_argvs("xray0", ["1.2.3.4"], True):
        keys = {t.split("=", 1)[0] for t in argv[5:] if "=" in t}
        assert keys <= {"name", "dir", "action", "enable", "description",
                        "remoteip", "localip"}
        assert "action=block" in argv and "dir=out" in argv


def test_v4_rule_leaves_server_and_loopback_reachable_and_blocks_the_rest():
    v4, _ = _rules(allow_lan=False)
    remote = v4["remoteip"].split(",")
    assert not _covers(remote, "1.2.3.4") and not _covers(remote, "127.0.0.1")
    assert _covers(remote, "8.8.8.8") and _covers(remote, "192.168.1.1")


def test_allow_lan_keeps_lan_link_local_and_dhcp_broadcast_reachable():
    v4, v6 = _rules(allow_lan=True)
    remote = v4["remoteip"].split(",")
    for ip in ("10.93.0.3", "172.16.5.5", "192.168.1.1", "169.254.1.1",
               "255.255.255.255"):
        assert not _covers(remote, ip), ip
    assert _covers(remote, "8.8.8.8")
    assert not _covers(v6["remoteip"].split(","), "fe80::1")


def test_v4_rule_never_matches_the_tunnels_own_source_address():
    v4, _ = _rules(allow_lan=False)
    local = v4["localip"].split(",")
    assert not _covers(local, win.TUN_ADDRESS)
    assert _covers(local, "192.168.1.143")


def test_v6_rule_keeps_server_and_loopback_and_blocks_other_v6():
    _, v6 = _rules(allow_lan=False)
    remote = v6["remoteip"].split(",")
    assert not _covers(remote, "2001:db8::1") and not _covers(remote, "::1")
    assert _covers(remote, "2606:4700:4700::1111")
    assert "localip" not in v6


# -- install -----------------------------------------------------------------
def test_install_adds_both_rules_and_is_active(fake):
    win.install("xray0", ["1.2.3.4"], allow_lan=True)
    assert set(fake.rules) == {win._V4_NAME, win._V6_NAME}
    assert win.is_active() is True


def test_install_never_touches_the_profile_policy(fake):
    win.install("xray0", ["1.2.3.4"], allow_lan=True)
    assert not any("set" in c and "allprofiles" in c for c in fake.calls)


def test_install_clears_a_leftover_first(fake):
    fake.rules[win._V4_NAME] = {"name": win._V4_NAME, "remoteip": "stale"}
    win.install("xray0", ["1.2.3.4"], allow_lan=False)
    assert fake.rules[win._V4_NAME]["remoteip"] != "stale"


def test_install_rolls_back_when_a_rule_is_refused(fake):
    fake.fail_add = win._V6_NAME
    with pytest.raises(FirewallError, match="could not add firewall rule"):
        win.install("xray0", ["1.2.3.4"], allow_lan=False)
    assert fake.rules == {}


# -- remove / is_active ------------------------------------------------------
def test_remove_deletes_both_rules(fake):
    win.install("xray0", ["1.2.3.4"], allow_lan=True)
    assert win.remove() == []
    assert fake.rules == {}
    assert win.is_active() is False


def test_remove_is_idempotent_when_empty(fake):
    assert win.remove() == []


def test_is_active_needs_both_rules(fake):
    assert win.is_active() is False
    win.install("xray0", ["1.2.3.4"], allow_lan=False)
    del fake.rules[win._V6_NAME]
    assert win.is_active() is False
