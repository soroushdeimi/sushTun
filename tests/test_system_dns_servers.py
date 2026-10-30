"""Pre-connect resolver discovery for dns.bypass_use_system_dns.

backup_dns is the restore record (empty on systemd-resolved, and for DHCP DNS
on macOS), so the effective resolvers are read by separate, best-effort code.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from xrayui.core import _net_posix as posix
from xrayui.core import connection, dns
from xrayui.core._net_common import DnsState

RESOLVECTL_LINK = "Link 2 (wlp3s0): 192.168.1.1 fe80::1%2\n"
RESOLVECTL_GLOBAL = "Global: 9.9.9.9 149.112.112.112\nLink 2 (wlp3s0):\n"
RESOLVECTL_EMPTY = "Link 2 (wlp3s0):\n"
SCUTIL = """DNS configuration

resolver #1
  search domain[0] : lan
  nameserver[0] : 192.168.1.1
  nameserver[1] : fe80::1%en0
  if_index : 6 (en0)
  flags    : Request A records
  reach    : 0x00020002 (Reachable,Directly Reachable Address)

resolver #2
  domain   : local
  options  : mdns
"""
SCUTIL_LOOPBACK_FIRST = """resolver #1
  nameserver[0] : 127.0.0.1

resolver #2
  nameserver[0] : 10.0.0.2
  nameserver[1] : 10.0.0.3
"""


def test_parse_resolvectl_link_line():
    assert posix.parse_resolvectl_dns(RESOLVECTL_LINK) == ["192.168.1.1", "fe80::1"]


def test_parse_resolvectl_global_only_ignores_link_lines():
    assert posix.parse_resolvectl_dns(RESOLVECTL_GLOBAL, global_only=True) == [
        "9.9.9.9", "149.112.112.112"]
    assert posix.parse_resolvectl_dns(RESOLVECTL_LINK, global_only=True) == []


@pytest.mark.parametrize("text", ["", RESOLVECTL_EMPTY, "garbage without colon", "Link 2 (x): not-an-ip\n"])
def test_parse_resolvectl_nothing_usable(text):
    assert posix.parse_resolvectl_dns(text) == []


def test_parse_resolvectl_strips_sni_suffix():
    assert posix.parse_resolvectl_dns("Link 3 (eth0): 1.1.1.1#cloudflare-dns.com\n") == ["1.1.1.1"]


def test_parse_scutil_takes_first_resolver_with_addresses():
    assert posix.parse_scutil_dns(SCUTIL) == ["192.168.1.1", "fe80::1"]
    assert posix.parse_scutil_dns(SCUTIL_LOOPBACK_FIRST) == ["10.0.0.2", "10.0.0.3"]
    assert posix.parse_scutil_dns("") == []


def test_parse_nameserver_lines_skips_comments_and_junk():
    lines = ["# generated", "nameserver 10.0.0.1", "search lan", "nameserver nope", "nameserver 10.0.0.2"]
    assert posix.parse_nameserver_lines(lines) == ["10.0.0.1", "10.0.0.2"]


def _run(stdout="", returncode=0):
    return lambda *a, **k: SimpleNamespace(stdout=stdout, returncode=returncode)


def test_resolved_uses_link_dns(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", False)
    monkeypatch.setattr(posix.proc, "run", _run(RESOLVECTL_LINK))
    assert posix.system_dns_servers("wlp3s0", DnsState("RESOLVED", [])) == ["192.168.1.1", "fe80::1"]


def test_resolved_falls_back_to_global(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", False)
    calls = []

    def fake(args, **k):
        calls.append(list(args))
        return SimpleNamespace(stdout=RESOLVECTL_EMPTY if args[-1] == "wlp3s0" else RESOLVECTL_GLOBAL,
                               returncode=0)

    monkeypatch.setattr(posix.proc, "run", fake)
    assert posix.system_dns_servers("wlp3s0", DnsState("RESOLVED", [])) == ["9.9.9.9", "149.112.112.112"]
    assert calls[0] == ["resolvectl", "dns", "wlp3s0"]


def test_file_mode_parses_the_backup_lines(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", False)
    monkeypatch.setattr(posix.proc, "run", lambda *a, **k: pytest.fail("no shell-out expected"))
    state = DnsState("FILE", ["nameserver 10.0.0.1", "search lan"])
    assert posix.system_dns_servers("eth0", state) == ["10.0.0.1"]


def test_parse_ipconfig_option_takes_every_address_and_ignores_noise():
    assert posix.parse_ipconfig_dns("45.159.149.19\n") == ["45.159.149.19"]
    assert posix.parse_ipconfig_dns("10.0.0.1 10.0.0.2\n10.0.0.1\n") == ["10.0.0.1", "10.0.0.2"]
    assert posix.parse_ipconfig_dns("") == []
    assert posix.parse_ipconfig_dns("The operation couldn't be completed.") == []


def test_macos_order_is_networksetup_then_dhcp_option_then_scutil(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", True)
    calls = []

    def fake(args, **k):
        calls.append(list(args))
        if args[0] == "ipconfig":
            return SimpleNamespace(stdout="45.159.149.19\n", returncode=0)
        return SimpleNamespace(stdout=SCUTIL, returncode=0)

    monkeypatch.setattr(posix.proc, "run", fake)
    # static servers recorded by networksetup win and need no shell-out
    assert posix.system_dns_servers("en0", DnsState("MACOS", ["Wi-Fi", "10.1.1.1"])) == ["10.1.1.1"]
    assert calls == []
    # DHCP DNS: the lease is read straight from the interface, even while
    # scutil only shows the 127.0.0.1 we put there ourselves
    assert posix.system_dns_servers("en0", DnsState("MACOS", ["Wi-Fi"])) == ["45.159.149.19"]
    assert calls == [["ipconfig", "getoption", "en0", "domain_name_server"]]


def test_macos_falls_back_to_scutil_when_the_lease_has_no_dns(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", True)

    def fake(args, **k):
        if args[0] == "ipconfig":
            return SimpleNamespace(stdout="", returncode=1)
        return SimpleNamespace(stdout=SCUTIL, returncode=0)

    monkeypatch.setattr(posix.proc, "run", fake)
    assert posix.system_dns_servers("en0", DnsState("MACOS", ["Wi-Fi"])) == ["192.168.1.1", "fe80::1"]


@pytest.mark.parametrize("failure", [
    subprocess.TimeoutExpired("resolvectl", 5), FileNotFoundError("resolvectl"), OSError("boom")])
def test_command_failures_yield_empty_list(monkeypatch, failure):
    monkeypatch.setattr(posix, "IS_MAC", False)

    def boom(*a, **k):
        raise failure

    monkeypatch.setattr(posix.proc, "run", boom)
    assert posix.system_dns_servers("eth0", DnsState("RESOLVED", [])) == []


def test_nonzero_exit_yields_empty_list(monkeypatch):
    monkeypatch.setattr(posix, "IS_MAC", False)
    monkeypatch.setattr(posix.proc, "run", _run(RESOLVECTL_LINK, returncode=1))
    assert posix.system_dns_servers("eth0", DnsState("RESOLVED", [])) == []


# -- connection glue -------------------------------------------------------

def test_flag_off_never_probes(monkeypatch):
    monkeypatch.setattr(connection.network, "system_dns_servers",
                        lambda *a: pytest.fail("must not probe when the flag is off"), raising=False)
    assert connection._system_dns({"bypass_use_system_dns": False}, "eth0", DnsState()) is None
    assert connection._system_dns({}, "eth0", DnsState()) is None


def test_flag_on_returns_probe_result_or_none(monkeypatch):
    monkeypatch.setattr(connection.network, "system_dns_servers",
                        lambda alias, state: ["10.0.0.1"], raising=False)
    assert connection._system_dns({"bypass_use_system_dns": True}, "eth0", DnsState()) == ["10.0.0.1"]
    monkeypatch.setattr(connection.network, "system_dns_servers", lambda alias, state: [], raising=False)
    assert connection._system_dns({"bypass_use_system_dns": True}, "eth0", DnsState()) is None


def test_probe_exception_cannot_break_connect(monkeypatch):
    def boom(alias, state):
        raise RuntimeError("probe blew up")

    monkeypatch.setattr(connection.network, "system_dns_servers", boom, raising=False)
    assert connection._system_dns({"bypass_use_system_dns": True}, "eth0", DnsState()) is None


# -- dns.py ----------------------------------------------------------------

def test_invalid_domestic_text_does_not_block_system_dns():
    d = {"bypass_use_system_dns": True, "domestic_servers": ["not a server !!"]}
    block, rules = dns.build_dns_and_rules(d, ["domain:example.com"], "1.2.3.4",
                                           system_dns=["192.168.1.1"])
    assert any(s.get("address") == "192.168.1.1" for s in block["servers"] if isinstance(s, dict))
    assert any(r.get("inboundTag") == ["direct-dns"] for r in rules)


def test_tun_range_is_derived_from_the_tun_constants():
    from xrayui.core._net_common import TUN_ADDRESS
    assert dns.clean_system_dns([TUN_ADDRESS, "172.19.0.1", "172.19.0.3", "172.19.0.4"]) == ["172.19.0.4"]
