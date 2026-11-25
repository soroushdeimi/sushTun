"""Tests for the MASQUE probe helper. No real networking, no real Xray."""
import threading
from types import SimpleNamespace

import pytest

from xrayui.core import masque_probe as mp


def _profile(**over):
    base = dict(
        name="m", protocol="masque", address="1.2.3.4", port=443,
        id="", username="", network="masque", security="tls",
        sni="example.com", fp="", alpn="", path="", host="",
        pcs="", vcn="",
        masque_http_version="h2", masque_private_key="", masque_public_key="",
        masque_addresses="", masque_remote_dns="",
    )
    base.update(over)
    return SimpleNamespace(**base)


# -- parse_endpoint ----------------------------------------------------------
def test_parse_endpoint_v4():
    assert mp.parse_endpoint("1.2.3.4:443") == ("1.2.3.4", 443)


def test_parse_endpoint_v6():
    assert mp.parse_endpoint("[2001:db8::1]:8443") == ("2001:db8::1", 8443)


@pytest.mark.parametrize("bad", ["", "1.2.3.4", "1.2.3.4:0", "1.2.3.4:70000",
                                 "1.2.3.4:abc", "[2001:db8::1", "[2001:db8::1]8443"])
def test_parse_endpoint_rejects(bad):
    with pytest.raises(ValueError):
        mp.parse_endpoint(bad)


# -- _build_config shape -----------------------------------------------------
def test_build_config_is_masque_single_carrier():
    p = _profile()
    cfg = mp._build_config(p, "1.2.3.4:443", 12345, "h2")
    ob = cfg["outbounds"][0]
    assert ob["protocol"] == "masque"
    assert ob["settings"] == {"address": "1.2.3.4", "port": 443}
    ss = ob["streamSettings"]
    assert ss["method"] == "masque"
    assert ss["security"] == "tls"
    # single carrier: alpn is exactly the one negotiated version
    assert ss["tlsSettings"]["alpn"] == ["h2"]
    assert "allowInsecure" not in ss and "realitySettings" not in ss
    # isolated local HTTP inbound, no tun/dns/api
    ib = cfg["inbounds"][0]
    assert ib["protocol"] == "http" and ib["listen"] == "127.0.0.1"
    assert not any(i.get("tag") in ("tun-in", "api") for i in cfg["inbounds"])
    assert "stats" not in cfg and "api" not in cfg


def test_build_config_h3_alpn():
    p = _profile(masque_http_version="h3")
    cfg = mp._build_config(p, "1.2.3.4:443", 1, "h3")
    assert cfg["outbounds"][0]["streamSettings"]["tlsSettings"]["alpn"] == ["h3"]


def test_build_config_remote_dns_must_be_ip():
    p = _profile(masque_remote_dns="1.1.1.1, 2606:4700:4700::1111")
    cfg = mp._build_config(p, "1.2.3.4:443", 1, "h2")
    assert cfg["outbounds"][0]["settings"]["remoteDNS"] == ["1.1.1.1", "2606:4700:4700::1111"]
    with pytest.raises(ValueError):
        mp._build_config(_profile(masque_remote_dns="dns.example.com"), "1.2.3.4:443", 1, "h2")


# -- _masque_settings auth rules --------------------------------------------
def test_basic_auth_both_or_neither():
    assert mp._masque_settings(_profile()) == {}
    ms = mp._masque_settings(_profile(username="u", id="p"))
    assert ms == {"user": "u", "pass": "p"}
    with pytest.raises(ValueError):
        mp._masque_settings(_profile(username="u"))  # partial
    with pytest.raises(ValueError):
        mp._masque_settings(_profile(id="p"))  # partial


def test_warp_identity_complete_and_partial():
    full = _profile(masque_private_key="PRIV", masque_public_key="PUB",
                    masque_addresses="172.16.0.2/32, 2606:4700::2/128")
    ms = mp._masque_settings(full)
    assert ms["warp"] == {"privateKey": "PRIV", "publicKey": "PUB",
                          "address": ["172.16.0.2/32", "2606:4700::2/128"]}
    # partial WARP identity rejected
    with pytest.raises(ValueError):
        mp._masque_settings(_profile(masque_private_key="PRIV", masque_public_key="PUB"))
    # WARP and basic auth are mutually exclusive
    with pytest.raises(ValueError):
        mp._masque_settings(_profile(username="u", id="p", masque_private_key="PRIV",
                                     masque_public_key="PUB", masque_addresses="1.1.1.1/32"))


# -- health url allowlist ----------------------------------------------------
def test_health_url_allowlist():
    assert mp._health_url_ok(mp.DEFAULT_HEALTH_URL)
    assert not mp._health_url_ok("http://www.google.com/generate_204")
    assert not mp._health_url_ok("https://evil.example.com/")
    assert not mp._health_url_ok("https://www.google.com.evil.com/")


# -- fake process plumbing ---------------------------------------------------
class FakePopen:
    def __init__(self, args, **kw):
        self.args = args
        self.terminated = False
        self.killed = False
        self.waited = 0
        FakePopen.instances.append(self)

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited += 1


def _run_probe(monkeypatch, profile, *, wait_state="ready", request=(12.0, None),
               cancel=None, timeout=8.0):
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: wait_state)
    monkeypatch.setattr(mp, "_request", lambda *a, **k: request)
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    res = mp.probe_endpoint(profile, xray_path=mp.Path("/xray"), timeout=timeout,
                            cancel_event=cancel)
    return res, FakePopen.instances


def test_probe_success(monkeypatch):
    res, pops = _run_probe(monkeypatch, _profile(), request=(12.5, None))
    assert res.ok is True
    assert res.latency_ms == 12.5
    assert res.error == ""
    assert res.http_version == "h2"
    assert res.endpoint == "1.2.3.4:443"
    # own process always stopped
    assert len(pops) == 1 and pops[0].terminated


def test_probe_bad_response_not_ok(monkeypatch):
    # A real HTTP error status is a data-plane answer, not success.
    res, _ = _run_probe(monkeypatch, _profile(), request=(None, "HTTP 500"))
    assert res.ok is False and res.latency_ms is None and res.error == "HTTP 500"


def test_probe_tls_only_is_not_success(monkeypatch):
    # Handshake completed but the request itself failed -> not ok.
    res, _ = _run_probe(monkeypatch, _profile(), request=(None, "timed out"))
    assert res.ok is False and res.error == "timed out"


def test_probe_startup_timeout(monkeypatch):
    res, pops = _run_probe(monkeypatch, _profile(), wait_state="timeout")
    assert res.ok is False and res.error == "startup timeout"
    assert pops[0].terminated


def test_probe_xray_exited(monkeypatch):
    res, _ = _run_probe(monkeypatch, _profile(), wait_state="exited")
    assert res.ok is False and res.error == "xray exited"


def test_probe_cancel_before(monkeypatch):
    # pre-set cancel: no process spawned at all
    ev = threading.Event()
    ev.set()
    res, pops = _run_probe(monkeypatch, _profile(), cancel=ev)
    assert res.ok is False and res.error == "cancelled"
    assert pops == []  # never started xray


def test_probe_cancel_during(monkeypatch):
    res, pops = _run_probe(monkeypatch, _profile(), wait_state="cancelled")
    assert res.ok is False and res.error == "cancelled"
    assert pops[0].terminated


def test_probe_invalid_version(monkeypatch):
    res, pops = _run_probe(monkeypatch, _profile(masque_http_version="h1"))
    assert res.ok is False and "invalid http version" in res.error
    assert pops == []


def test_probe_disallowed_health_url(monkeypatch):
    FakePopen.instances = []
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"),
                            health_url="https://evil.example.com/")
    assert res.ok is False and "disallowed health url" in res.error
    assert FakePopen.instances == []


def test_probe_does_not_mutate_profile():
    p = _profile()
    before = vars(p)
    # call with a cancel already set so no process is spawned
    ev = threading.Event()
    ev.set()
    mp.probe_endpoint(p, xray_path=mp.Path("/xray"), cancel_event=ev)
    assert vars(p) == before


# -- scan_endpoints bounds ---------------------------------------------------
def test_scan_rejects_bad_max_workers(monkeypatch):
    with pytest.raises(ValueError):
        mp.scan_endpoints(_profile(), ["1.2.3.4:443"], xray_path=mp.Path("/x"),
                          max_workers=0)
    with pytest.raises(ValueError):
        mp.scan_endpoints(_profile(), ["1.2.3.4:443"], xray_path=mp.Path("/x"),
                          max_workers=6)


def test_scan_rejects_too_many_endpoints(monkeypatch):
    eps = [f"10.0.0.{i}:443" for i in range(mp.MAX_ENDPOINTS + 1)]
    with pytest.raises(ValueError):
        mp.scan_endpoints(_profile(), eps, xray_path=mp.Path("/x"))


def test_scan_bounds_constants():
    assert mp.MAX_ENDPOINTS == 64
    assert mp.MAX_WORKERS == 5


def test_scan_runs_each_endpoint_and_stops_processes(monkeypatch):
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp, "_request", lambda *a, **k: (5.0, None))
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    eps = ["1.1.1.1:443", "2.2.2.2:443", "3.3.3.3:443"]
    results = mp.scan_endpoints(_profile(), eps, xray_path=mp.Path("/x"), max_workers=3)
    assert [r.endpoint for r in results] == eps  # input order preserved
    assert all(r.ok for r in results)
    assert len(FakePopen.instances) == 3
    assert all(p.terminated for p in FakePopen.instances)


def test_scan_malformed_endpoint_reports_not_raises(monkeypatch):
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp, "_request", lambda *a, **k: (5.0, None))
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    results = mp.scan_endpoints(_profile(), ["1.1.1.1:443", "bad-endpoint"],
                                xray_path=mp.Path("/x"))
    assert results[0].ok is True
    assert results[1].ok is False and "invalid endpoint" in results[1].error
