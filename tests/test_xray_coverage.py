"""The Xray key inventory (docs/xray) stays complete and honest.

keys.json is generated from the core's Go source by scripts/xray_keys.py;
classification.toml and status.toml are kept by hand. These tests fail when a
client-side key has no status, when a status claims support with a wildcard,
when the report is stale, or when sushTun writes a key the bundled core does
not know (Go drops unknown keys silently, so such a key simply does nothing).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from xrayui.core import render, routing, settings
from xrayui.core.profiles import Profile

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "xray"

_spec = importlib.util.spec_from_file_location("xray_keys", ROOT / "scripts" / "xray_keys.py")
xk = importlib.util.module_from_spec(_spec)
sys.modules["xray_keys"] = xk  # dataclasses look their module up while being built
_spec.loader.exec_module(xk)

# Keys sushTun writes today that the bundled core does not know. Each is a
# finding in docs/xray/DESIGN.md; remove a line when its fix lands.
KNOWN_UNKNOWN = {
    # Ignored by 26.3.27; newer cores accept it, so a core upgrade changes
    # behaviour without any change here.
    "inbounds[].settings{protocol=tun}.dns",
    # network h2/http: the core removed this transport and refuses to start.
    "outbounds[].streamSettings.httpSettings",
    # The legacy `"type": "field"`; ignored, harmless.
    "routing.rules[].type",
}


@pytest.fixture(scope="module")
def keys():
    return json.loads((DOCS / "keys.json").read_text(encoding="utf-8"))["keys"]


@pytest.fixture(scope="module")
def rules_and_status():
    return xk.load_rules()


def _client_keys(keys, rules):
    return [k for k, e in keys.items()
            if xk.in_baseline(e) and xk.classify(k, rules)["class"] == "client"]


def test_every_key_is_classified_and_every_exclusion_says_why(keys, rules_and_status):
    rules, _ = rules_and_status
    unclassified = [k for k in keys if xk.classify(k, rules) is None]
    assert unclassified == []
    for rule in rules:
        assert rule["class"] in ("client", "server", "internal")
        if rule["class"] != "client":
            assert rule.get("reason"), rule["match"]


def test_every_client_key_has_a_status(keys, rules_and_status):
    rules, statuses = rules_and_status
    missing = [k for k in _client_keys(keys, rules) if xk.status_of(k, statuses) is None]
    assert missing == [], "add these to docs/xray/status.toml"


def test_support_is_never_claimed_by_wildcard(rules_and_status):
    _, statuses = rules_and_status
    for entry in statuses:
        assert entry["status"] in ("full", "partial", "imported", "alias", "unsupported")
        if entry["status"] in ("full", "partial"):
            assert not any("*" in p for p in entry["match"]), entry["match"]


def test_every_status_entry_matches_a_key_and_names_real_files(keys, rules_and_status):
    rules, statuses = rules_and_status
    client = _client_keys(keys, rules)
    for entry in statuses:
        assert any(xk.first_match(k, [entry]) for k in client), entry["match"]
        for f in entry.get("files", []):
            assert (ROOT / f).exists(), f


def test_the_coverage_report_is_up_to_date(keys):
    data = json.loads((DOCS / "keys.json").read_text(encoding="utf-8"))
    assert (DOCS / "COVERAGE.md").read_text(encoding="utf-8") == xk.report(data), (
        "run: python scripts/xray_keys.py report > docs/xray/COVERAGE.md")


def _profiles() -> list[Profile]:
    tls = {"address": "a.example", "id": "x", "security": "tls", "sni": "a.example"}
    return [
        Profile(protocol="vless", address="a.example", id="x", security="reality", sni="a",
                pbk="k", sid="1", fp="chrome", network="tcp", flow="xtls-rprx-vision",
                pqv="A" * 2603),
        Profile(protocol="vless", network="ws", path="/", host="h", **tls),
        Profile(protocol="vless", network="xhttp", path="/", xhttp_mode="auto",
                xhttp_extra='{"xmux": {"maxConcurrency": "16-32"}}', **tls),
        Profile(protocol="vless", network="grpc", service_name="s", **tls),
        Profile(protocol="vless", network="httpupgrade", path="/", host="h", **tls),
        Profile(protocol="vless", network="h2", path="/", **tls),
        Profile(protocol="vmess", address="a.example", id="x", network="tcp",
                header_type="http", path="/", host="h"),
        Profile(protocol="trojan", **tls),
        Profile(protocol="shadowsocks", address="a.example", id="x", ss_method="aes-128-gcm"),
        Profile(protocol="hysteria2", address="a.example", id="x", hy2_obfs_password="o",
                hy2_ports="1000-2000", hy2_up_mbps=10, hy2_down_mbps=50),
        Profile(protocol="wireguard", address="a.example", id="x", pbk="k",
                wg_reserved="1,2,3", wg_local_address="10.0.0.2/32", wg_keepalive=25),
    ]


def test_sushtun_writes_no_key_the_bundled_core_ignores(keys):
    # Every optional path switched on, so each overlay gets looked at.
    core = json.loads(json.dumps(settings.DEFAULTS["core"]))
    core["fragment"]["enabled"] = True
    core["mux"]["enabled"] = True
    core.update(allow_lan=True, lan_user="u", lan_pass="p", default_fp="chrome")
    dns = json.loads(json.dumps(settings.DEFAULTS["dns"]))
    dns.update(domestic_servers=["1.1.1.1"], parallel_query=True, serve_stale=True,
               hosts=["a.example = 1.2.3.4"], remote_via_tunnel=True)
    found = set()
    for profile in _profiles():
        cfg = json.loads(render.build_text(
            profile=profile, iface_alias="eth0",
            routing_rules=routing.build_rules(settings.DEFAULTS["routing"]),
            domain_strategy="IPIfNonMatch", stats=True, log_level="warning",
            dns_cfg=dns, tun_mtu=1400, server_ip="1.2.3.4", core_cfg=core))
        found |= set(xk.unknown_paths(cfg, keys))
    assert found == KNOWN_UNKNOWN


def test_unknown_paths_catches_a_misspelt_key(keys):
    cfg = {"outbounds": [{"protocol": "vless", "settings": {"vnext": []},
                          "streamSettings": {"tlsSettings": {"serverNme": "x"}}}]}
    assert xk.unknown_paths(cfg, keys) == ["outbounds[].streamSettings.tlsSettings.serverNme"]
