"""Leak check: verdict logic, real-IP masking, and the read-only DNS/IPv6
audit parsers (all three OSes, from captured-style fixture text)."""
from __future__ import annotations

import io

import pytest

from xrayui.core import alerts, geo_exit, leakcheck


# -- mask_ip -----------------------------------------------------------------
def test_mask_ip_hides_the_last_two_octets():
    assert leakcheck.mask_ip("152.233.20.199") == "152.233.*.*"


@pytest.mark.parametrize("bad", ["", None, "not-an-ip", "1.2.3", "1.2.3.4.5",
                                 "1.2.3.x", "1.2.3.4/24"])
def test_mask_ip_refuses_unrecognised_values(bad):
    assert leakcheck.mask_ip(bad) is None


def test_mask_ip_strips_surrounding_whitespace():
    assert leakcheck.mask_ip("  127.0.0.1  ") == "127.0.*.*"


def test_mask_ip_keeps_first_two_hextets_of_ipv6():
    assert leakcheck.mask_ip("2001:db8:85a3::8a2e:370:7334") == "2001:db8::"


# -- check (pure verdict) ----------------------------------------------------
def _exit(country, ip):
    return geo_exit.ExitInfo(country, ip)


def test_check_ok_when_exit_is_a_foreign_ip():
    v = leakcheck.check(_exit("de", "152.233.20.199"), "1.2.3.4")
    assert v.status == leakcheck.OK
    assert v.exit_country == "de"
    assert v.real_ip_masked == "1.2.*.*"


def test_check_exit_is_iran():
    v = leakcheck.check(_exit("ir", "177.10.1.1"), "1.2.3.4")
    assert v.status == leakcheck.EXIT_IS_IRAN


def test_check_ip_matches_real():
    v = leakcheck.check(_exit("de", "1.2.3.4"), "1.2.3.4")
    assert v.status == leakcheck.IP_MATCHES_REAL
    assert v.real_ip_masked == "1.2.*.*"


def test_check_never_ok_when_the_probe_failed():
    v = leakcheck.check(None, "1.2.3.4")
    assert v.status == leakcheck.UNKNOWN
    assert not leakcheck.is_active(v)


def test_check_ok_when_real_ip_is_unknown_but_exit_is_foreign():
    # No real IP to compare against, but the exit is a foreign country: the
    # tunnel is doing its job, so this is OK, not UNKNOWN.
    v = leakcheck.check(_exit("de", "152.233.20.199"), None)
    assert v.status == leakcheck.OK


def test_check_iran_wins_over_ip_match():
    # Both bad; the more specific (Iran) verdict is reported.
    v = leakcheck.check(_exit("ir", "1.2.3.4"), "1.2.3.4")
    assert v.status == leakcheck.EXIT_IS_IRAN


def test_status_message_and_is_active():
    ok = leakcheck.check(_exit("de", "152.233.20.199"), "1.2.3.4")
    assert leakcheck.is_active(ok)
    assert leakcheck.status(ok) == "protected"
    assert leakcheck.message(ok) == leakcheck.MSG_OK
    unknown = leakcheck.check(None, None)
    assert not leakcheck.is_active(unknown)
    assert leakcheck.status(unknown) == "unknown"
    assert leakcheck.message(unknown) == leakcheck.MSG_UNKNOWN


# -- build_probe_config ------------------------------------------------------
def test_build_probe_config_pins_freedom_to_the_physical_iface():
    cfg = leakcheck.build_probe_config(10808, "en0")
    assert cfg["inbounds"][0]["protocol"] == "http"
    assert cfg["inbounds"][0]["port"] == 10808
    out = cfg["outbounds"][0]
    assert out["protocol"] == "freedom"
    assert out["sockopt"]["interface"] == "en0"
    assert cfg["routing"]["rules"][0]["outboundTag"] == "direct"
    # The placeholder must be substituted, never left in the config.
    import json
    assert "__IFACE__" not in json.dumps(cfg)


# -- RealIpCache -------------------------------------------------------------
def test_real_ip_cache_probes_once_and_reuses():
    calls = []

    def probe():
        calls.append(1)
        return "1.2.3.4"

    cache = leakcheck.RealIpCache()
    assert cache.get(probe) == "1.2.3.4"
    assert cache.get(probe) == "1.2.3.4"
    assert len(calls) == 1  # probed once, then served from cache


def test_real_ip_cache_retries_after_a_failed_probe():
    results = iter([None, "1.2.3.4"])

    def probe():
        return next(results)

    cache = leakcheck.RealIpCache()
    assert cache.get(probe) is None  # not cached
    assert cache.get(probe) == "1.2.3.4"  # retried, then cached
    assert cache.get(probe) == "1.2.3.4"


def test_real_ip_cache_clear_forgets():
    cache = leakcheck.RealIpCache()
    cache.get(lambda: "1.2.3.4")
    cache.clear()
    calls = []

    def probe():
        calls.append(1)
        return "5.6.7.8"

    assert cache.get(probe) == "5.6.7.8"
    assert len(calls) == 1


# -- run_check (wired, but with the network faked) ---------------------------
class _Opener:
    def __init__(self, body=None, error=None):
        self.body, self.error = body, error

    def open(self, url, timeout=None):
        if self.error:
            raise self.error
        resp = io.BytesIO(self.body.encode())
        resp.__enter__ = lambda: resp
        return resp


def test_run_check_ok(monkeypatch):
    monkeypatch.setattr(leakcheck.geo_exit, "detect",
                        lambda opener, timeout: _exit("de", "152.233.20.199"))
    monkeypatch.setattr(leakcheck, "_run_real_ip_probe",
                        lambda iface, timeout=8.0: "1.2.3.4")
    v = leakcheck.run_check(None, "en0", leakcheck.RealIpCache())
    assert v.status == leakcheck.OK
    assert v.real_ip_masked == "1.2.*.*"


def test_run_check_never_ok_when_tunnel_probe_fails(monkeypatch):
    # The tunnel probe raises (xray died mid-check): must be UNKNOWN, not OK.
    def boom(opener, timeout):
        raise OSError("tunnel down")

    monkeypatch.setattr(leakcheck.geo_exit, "detect", boom)
    monkeypatch.setattr(leakcheck, "_run_real_ip_probe",
                        lambda iface, timeout=8.0: "1.2.3.4")
    v = leakcheck.run_check(None, "en0", leakcheck.RealIpCache())
    assert v.status == leakcheck.UNKNOWN


def test_run_check_never_raises_when_the_real_ip_probe_fails(monkeypatch):
    monkeypatch.setattr(leakcheck.geo_exit, "detect",
                        lambda opener, timeout: _exit("de", "152.233.20.199"))

    def bad_probe(iface, timeout=8.0):
        raise OSError("no physical interface")

    monkeypatch.setattr(leakcheck, "_run_real_ip_probe", bad_probe)
    v = leakcheck.run_check(None, "en0", leakcheck.RealIpCache())
    # Real IP unknown, but the exit is foreign: still OK, and no exception.
    assert v.status == leakcheck.OK
    assert v.real_ip_masked is None


# -- DNS audit parsers -------------------------------------------------------
RESOLVECTL = """\
Global: 1.1.1.1
Link 2 (eth0): 192.168.1.1
Link 10 (xray0): 172.19.0.1
"""

SCUTIL = """\
DNS configuration

resolver #1
  nameserver[0] : 127.0.0.1
  flags    : Request A records, Request AAAA records
  reach    : 0x00030002 (Reachable,Local Address,Directly Reachable Address)

resolver #2
  domain   : local
  options  : mdns
  timeout  : 5
  flags    : Request A records
  reach    : 0x00000000 (Not Reachable)
  order    : 300000

resolver #3
  nameserver[0] : 192.168.1.1
  flags    : Request A records
  reach    : 0x00030002 (Reachable,Local Address,Directly Reachable Address)
"""

GETDNSC = """\
InterfaceAlias  ServerAddresses
--------------  ---------------
Ethernet        {192.168.1.1}
Wi-Fi           {127.0.0.1}
"""


def test_parse_resolvectl_dns_audit():
    entries = leakcheck.parse_resolvectl_dns_audit(RESOLVECTL)
    assert entries == [
        leakcheck.ResolverEntry("Global", ("1.1.1.1",)),
        leakcheck.ResolverEntry("eth0", ("192.168.1.1",)),
        leakcheck.ResolverEntry("xray0", ("172.19.0.1",)),
    ]


def test_parse_resolvectl_dns_audit_strips_sni_and_scope():
    text = "Link 3 (eth0): 1.1.1.1#cloudflare-dns.com fe80::1%eth0\n"
    entries = leakcheck.parse_resolvectl_dns_audit(text)
    assert entries == [leakcheck.ResolverEntry("eth0", ("1.1.1.1", "fe80::1"))]


def test_parse_scutil_dns_audit_skips_mdns_blocks():
    entries = leakcheck.parse_scutil_dns_audit(SCUTIL)
    assert entries == [
        leakcheck.ResolverEntry("1", ("127.0.0.1",)),
        leakcheck.ResolverEntry("3", ("192.168.1.1",)),
    ]


def test_parse_getdnscclient_dns_audit():
    entries = leakcheck.parse_getdnscclient_dns_audit(GETDNSC)
    assert entries == [
        leakcheck.ResolverEntry("Ethernet", ("192.168.1.1",)),
        leakcheck.ResolverEntry("Wi-Fi", ("127.0.0.1",)),
    ]


def test_parse_getdnscclient_dns_audit_handles_multi_server_and_header():
    text = ("InterfaceAlias  ServerAddresses\n"
            "--------------  ---------------\n"
            "Ethernet        {1.1.1.1, 8.8.8.8}\n")
    entries = leakcheck.parse_getdnscclient_dns_audit(text)
    assert entries == [leakcheck.ResolverEntry("Ethernet", ("1.1.1.1", "8.8.8.8"))]


def test_dns_leaks_flags_only_the_non_tunnel_resolvers():
    entries = leakcheck.parse_resolvectl_dns_audit(RESOLVECTL)
    leaks = leakcheck.dns_leaks(entries, {"127.0.0.1", "172.19.0.1"})
    assert [e.name for e in leaks] == ["Global", "eth0"]


def test_dns_leaks_allows_loopback_even_when_not_listed():
    entries = [leakcheck.ResolverEntry("Wi-Fi", ("127.0.0.1",))]
    assert leakcheck.dns_leaks(entries, set()) == []


def test_dns_leaks_empty_when_everything_is_the_tunnel():
    entries = [leakcheck.ResolverEntry("xray0", ("172.19.0.1",))]
    assert leakcheck.dns_leaks(entries, {"172.19.0.1"}) == []


# -- IPv6 default-route parsers ----------------------------------------------
IP6_LINUX = """\
default via fe80::1 dev eth0 proto ra metric 100 expires 115sec pref medium
default via fe80::1 dev xray0 proto static metric 100
fe80::/64 dev eth0 proto kernel metric 256 pref medium
fe80::/64 dev xray0 proto kernel metric 256 pref medium
"""

IP6_MACOS = """\
Routing tables

Internet6:
Destination        Gateway            Flags    Netif Expire
default            fe80::%utun0       UGcIg    utun0
default            fe80::%en0         UGcIg    en0
::1                ::1                UHL      lo0
fe80::%en0/64      link#14            UCI      en0
"""

IP6_WINDOWS = """\
===========================================================================
Interface Metric
New Routes:
===========================================================================
Active Routes:
If Metric Network Destination     Gateway
 4    256 fe80::14a4:370a:b39d:4e1d/128 0.0.0.0
 4    256 ::/0                       fe80::1
 12   256 ::/0                       fe80::1%utun233
 1    256 ::1/128                    0.0.0.0
"""


def test_parse_ipv6_default_linux():
    assert leakcheck.parse_ipv6_default_linux(IP6_LINUX) == ["eth0", "xray0"]


def test_parse_ipv6_default_macos():
    assert leakcheck.parse_ipv6_default_macos(IP6_MACOS) == ["utun0", "en0"]


def test_parse_ipv6_default_windows():
    assert leakcheck.parse_ipv6_default_windows(IP6_WINDOWS) == ["4", "12"]


def test_ipv6_leak_flags_only_the_non_tunnel_device():
    assert leakcheck.ipv6_leak(["eth0", "xray0"], {"xray0"}) == ["eth0"]


def test_ipv6_leak_empty_when_only_the_tunnel_has_a_default():
    assert leakcheck.ipv6_leak(["xray0"], {"xray0"}) == []


def test_ipv6_leak_empty_when_there_is_no_default_route():
    assert leakcheck.ipv6_leak([], {"xray0"}) == []


# -- alerts ------------------------------------------------------------------
def test_tunnel_lost_only_when_connected_but_xray_gone():
    assert alerts.tunnel_lost(True, False) is True
    assert alerts.tunnel_lost(True, True) is False
    assert alerts.tunnel_lost(False, False) is False
    assert alerts.tunnel_lost(False, True) is False


def test_current_alerts_vpn_dropped():
    got = alerts.current_alerts(state_connected=True, xray_running=False)
    assert [a.key for a in got] == ["vpn:dropped"]
    assert got[0].level == "critical"


def test_current_alerts_ip_leak_from_verdict():
    v = leakcheck.check(_exit("ir", "177.10.1.1"), "1.2.3.4")
    got = alerts.current_alerts(state_connected=True, xray_running=True,
                                verdict=v)
    assert [a.key for a in got] == ["leak:ip:iran"]
    assert got[0].level == "critical"


def test_current_alerts_ip_matches_real():
    v = leakcheck.check(_exit("de", "1.2.3.4"), "1.2.3.4")
    got = alerts.current_alerts(state_connected=True, xray_running=True,
                                verdict=v)
    assert [a.key for a in got] == ["leak:ip:real"]


def test_current_alerts_ok_verdict_raises_nothing():
    v = leakcheck.check(_exit("de", "152.233.20.199"), "1.2.3.4")
    assert alerts.current_alerts(state_connected=True, xray_running=True,
                                 verdict=v) == []


def test_current_alerts_dns_and_ipv6_from_audit():
    dns = leakcheck.DnsAudit(
        (leakcheck.ResolverEntry("eth0", ("192.168.1.1",)),),
        (leakcheck.ResolverEntry("eth0", ("192.168.1.1",)),))
    ipv6 = leakcheck.Ipv6Audit(("eth0", "xray0"), ("eth0",))
    got = alerts.current_alerts(state_connected=True, xray_running=True,
                                dns_audit=dns, ipv6_audit=ipv6)
    assert [a.key for a in got] == ["leak:dns", "leak:ipv6"]
    assert all(a.level == "warning" for a in got)


def test_current_alerts_clean_audit_raises_nothing():
    dns = leakcheck.DnsAudit((), ())
    ipv6 = leakcheck.Ipv6Audit(("xray0",), ())
    assert alerts.current_alerts(state_connected=True, xray_running=True,
                                 dns_audit=dns, ipv6_audit=ipv6) == []


def test_current_alerts_clears_when_fixed():
    # The same inputs with the condition gone produce no alert: the UI shows
    # these every tick, so the alert disappears the moment it is fixed.
    v = leakcheck.check(_exit("de", "152.233.20.199"), "1.2.3.4")
    assert alerts.current_alerts(state_connected=True, xray_running=True,
                                 verdict=v) == []


def test_current_alerts_combines_independent_findings():
    v = leakcheck.check(_exit("ir", "177.10.1.1"), "1.2.3.4")
    dns = leakcheck.DnsAudit(
        (leakcheck.ResolverEntry("eth0", ("192.168.1.1",)),),
        (leakcheck.ResolverEntry("eth0", ("192.168.1.1",)),))
    got = alerts.current_alerts(state_connected=True, xray_running=True,
                                verdict=v, dns_audit=dns)
    assert [a.key for a in got] == ["leak:ip:iran", "leak:dns"]
