"""Linux firewall backend: nftables rule text, the iptables fallback, ordering,
rollback, and idempotency. The real nft/iptables cannot be run here, so a
recording fake captures every argv and the generated nft script is checked for
structure (allow rules before the drop).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from xrayui import paths
from xrayui.core import _firewall_linux as lin
from xrayui.core._firewall_common import FirewallError

NS = SimpleNamespace


def _record(monkeypatch, tmp_path, *, has_nft=True, has_ipt=False):
    ran: list[list[str]] = []

    def fake_run(args, **_k):
        ran.append(list(args))
        return NS(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(lin.proc, "run", fake_run)
    monkeypatch.setattr(lin, "_has_nft", lambda: has_nft)
    monkeypatch.setattr(lin.shutil, "which",
                        lambda name: "/usr/bin/" + name
                        if (name == "nft" and has_nft)
                        or (name in ("iptables", "ip6tables") and has_ipt)
                        else None)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    return ran


# -- nftables rule text ------------------------------------------------------
def test_nft_script_allows_then_drops():
    script = lin.build_nft("xray0", ["1.2.3.4", "2001:db8::1"], allow_lan=True)
    assert "table inet sushtun {" in script
    assert 'oifname "xray0" accept' in script
    assert "ip daddr 1.2.3.4 accept" in script
    assert "ip6 daddr 2001:db8::1 accept" in script
    assert 'oifname "lo" accept' in script
    assert "udp dport 67 accept" in script
    assert "meta nfproto ipv6 udp dport 546 accept" in script
    assert "ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16 } accept" in script
    assert "ip6 daddr fe80::/10 accept" in script
    assert script.rstrip().endswith("}")
    # The drop is the last rule in the chain.
    assert script.rstrip().rsplit("}", 2)[0].rstrip().endswith("drop")


def test_nft_script_omits_lan_when_disabled():
    script = lin.build_nft("xray0", ["1.2.3.4"], allow_lan=False)
    assert "10.0.0.0/8" not in script
    assert "fe80::/10" not in script
    assert "udp dport 67" not in script


def test_nft_script_drops_unparseable_ips():
    script = lin.build_nft("xray0", ["bogus", "1.2.3.4"], allow_lan=False)
    assert "bogus" not in script
    assert "ip daddr 1.2.3.4 accept" in script


# -- nftables install / remove ----------------------------------------------
def test_nft_install_deletes_then_loads_table(monkeypatch, tmp_path):
    ran = _record(monkeypatch, tmp_path, has_nft=True)
    monkeypatch.setattr(lin, "_nft_active", lambda: True)
    lin.install("xray0", ["1.2.3.4"], allow_lan=True)

    # Delete the old table first, then load the whole table in one -f.
    assert ran[0] == ["nft", "delete", "table", "inet", "sushtun"]
    assert any(c[:2] == ["nft", "-f"] for c in ran)


def test_nft_install_fails_when_not_active(monkeypatch, tmp_path):
    _record(monkeypatch, tmp_path, has_nft=True)
    monkeypatch.setattr(lin, "_nft_active", lambda: False)
    with pytest.raises(FirewallError, match="verified"):
        lin.install("xray0", ["1.2.3.4"], allow_lan=True)


def test_nft_remove_deletes_whole_table(monkeypatch, tmp_path):
    ran = _record(monkeypatch, tmp_path, has_nft=True)
    assert lin.remove() == []
    assert ran == [["nft", "delete", "table", "inet", "sushtun"]]


def test_nft_is_active_requires_the_drop(monkeypatch, tmp_path):
    _record(monkeypatch, tmp_path, has_nft=True)

    def list_table(args, **_k):
        if args[:2] == ["nft", "list"]:
            return NS(returncode=0, stdout="drop" if _active[0] else "")
        return NS(returncode=0, stdout="", stderr="")

    _active = [False]
    monkeypatch.setattr(lin.proc, "run", list_table)
    assert lin.is_active() is False
    _active[0] = True
    assert lin.is_active() is True


# -- iptables fallback -------------------------------------------------------
def test_iptables_rules_allow_then_drop(monkeypatch, tmp_path):
    _record(monkeypatch, tmp_path, has_nft=False, has_ipt=True)
    rules = lin._ipt_rules("xray0", ["1.2.3.4"], allow_lan=True, v6=False)
    # First rule allows the tunnel, last rule drops.
    assert rules[0][-4:] == ["-o", "xray0", "-j", "ACCEPT"]
    assert rules[-1] == ["iptables", "-A", "SUSHTUN", "-j", "DROP"]
    assert ["iptables", "-A", "SUSHTUN", "-d", "1.2.3.4", "-j", "ACCEPT"] in rules
    assert ["iptables", "-A", "SUSHTUN", "-o", "lo", "-j", "ACCEPT"] in rules


def test_iptables_install_hooks_output_after_building_chain(monkeypatch, tmp_path):
    ran = _record(monkeypatch, tmp_path, has_nft=False, has_ipt=True)
    monkeypatch.setattr(lin, "_jump_present", lambda ipt: False)
    monkeypatch.setattr(lin, "_ipt_active", lambda: True)
    lin.install("xray0", ["1.2.3.4"], allow_lan=False)

    # The OUTPUT jump is added only after the chain rules are in place.
    jump = next(i for i, c in enumerate(ran) if c[:3] == ["iptables", "-I", "OUTPUT"])
    first_rule = next(i for i, c in enumerate(ran) if c[:3] == ["iptables", "-A", "SUSHTUN"])
    assert jump > first_rule


def test_iptables_install_rolls_back_on_failure(monkeypatch, tmp_path):
    ran = _record(monkeypatch, tmp_path, has_nft=False, has_ipt=True)
    monkeypatch.setattr(lin, "_jump_present", lambda ipt: False)
    # v4 installs fine, v6 fails verification.
    monkeypatch.setattr(lin, "_ipt_active", lambda: False)
    with pytest.raises(FirewallError, match="verified"):
        lin.install("xray0", ["1.2.3.4"], allow_lan=False)
    # Both families were rolled back: the chains were flushed and deleted.
    assert ["iptables", "-F", "SUSHTUN"] in ran
    assert ["iptables", "-X", "SUSHTUN"] in ran
    assert ["ip6tables", "-F", "SUSHTUN"] in ran
    assert ["ip6tables", "-X", "SUSHTUN"] in ran


def test_iptables_remove_deletes_jump_chain(monkeypatch, tmp_path):
    ran = _record(monkeypatch, tmp_path, has_nft=False, has_ipt=True)
    monkeypatch.setattr(lin, "_jump_present", lambda ipt: True)
    assert lin.remove() == []
    assert ["iptables", "-D", "OUTPUT", "-j", "SUSHTUN"] in ran
    assert ["iptables", "-X", "SUSHTUN"] in ran
    assert ["ip6tables", "-D", "OUTPUT", "-j", "SUSHTUN"] in ran


# -- unsupported -------------------------------------------------------------
def test_install_unsupported_when_no_tools(monkeypatch, tmp_path):
    _record(monkeypatch, tmp_path, has_nft=False, has_ipt=False)
    with pytest.raises(FirewallError, match="neither nft nor iptables"):
        lin.install("xray0", ["1.2.3.4"], allow_lan=True)
