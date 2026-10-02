"""Ordered chains persist references and fail closed before rendering."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import backup, chains, outbounds, render, settings
from xrayui.core.exits import Exit
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


def profiles(count=3):
    return [Profile(uid=f"hop-{n}", name=f"Hop {n}", address=f"hop{n}.example",
                    id="11111111-1111-1111-1111-111111111111") for n in range(count)]


def chain_for(items):
    return chains.Chain(uid="ordered", name="Ordered", hops=[p.uid for p in items])


@pytest.mark.parametrize("count", [2, 3, 8])
def test_store_preserves_order_and_references(monkeypatch, tmp_path, count):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    items = profiles(count)
    chain = chain_for(items)
    store = chains.ChainStore()
    store.save(chain)
    assert store.file == tmp_path / "chains.json"
    assert chains.ChainStore().get(chain.uid) == chain
    assert store.list() == [chain]
    chain.name = "Renamed"
    store.save(chain)
    assert store.list() == [chain]
    assert "address" not in store.file.read_text()
    store.delete(chain.uid)
    assert store.list() == []


@pytest.mark.parametrize("count", [0, 1, 9])
def test_hop_limits(count):
    items = profiles(count)
    assert any("2" in msg and "8" in msg for msg in chains.validate(chain_for(items), items))


def test_missing_duplicate_and_malformed_references():
    items = profiles()
    chain = chain_for(items)
    chain.hops = [items[0].uid, items[0].uid, "gone", "../escape", {}, None]
    problems = " ".join(chains.validate(chain, items)).lower()
    assert "twice" in problems and "gone" in problems and "invalid" in problems
    with pytest.raises(ValueError):
        chains.resolve(chain, items)


@pytest.mark.parametrize("hops", [None, "hop-0", {}, ["bad/name", "hop-1"]])
def test_hand_edited_hops_fail_closed(hops):
    chain = chains.Chain.from_dict({"uid": "ordered", "name": "Broken", "hops": hops})
    assert chains.validate(chain, profiles())


@pytest.mark.parametrize("protocol", ["vless", "vmess", "trojan", "shadowsocks"])
def test_supported_protocols(protocol):
    items = profiles(2)
    items[1].protocol = protocol
    items[1].ss_method = "aes-128-gcm"
    assert chains.validate(chain_for(items), items) == []


@pytest.mark.parametrize("protocol", ["hysteria2", "wireguard", "socks", "unknown"])
def test_unverified_protocols_rejected(protocol):
    items = profiles(2)
    items[1].protocol = protocol
    assert protocol in " ".join(chains.validate(chain_for(items), items))


@pytest.mark.parametrize("changes,reason", [
    ({"flow": "xtls-rprx-vision"}, "flow"),
    ({"network": "xhttp", "xhttp_extra": '{"downloadSettings":{"address":"elsewhere"}}'}, "xhttp"),
    ({"network": "kcp"}, "kcp"),
    ({"network": "ws"}, "ws"),
    ({"network": "h2"}, "h2"),
    ({"address": ""}, "address"),
    ({"id": ""}, "credential"),
])
def test_unverified_combinations_and_incomplete_profiles_rejected(changes, reason):
    items = profiles(2)
    for key, value in changes.items():
        setattr(items[0], key, value)
    assert reason in " ".join(chains.validate(chain_for(items), items)).lower()


def test_resolved_plan_is_detached_from_later_edits():
    items = profiles()
    chain = chain_for(items)
    plan = chains.resolve(chain, items)
    items[0].address = "changed"
    chain.hops.reverse()
    plan.profiles[0].address = "also changed"
    assert plan.entry.address == "hop0.example"
    assert plan.exit.uid == "hop-2"
    assert plan.uid == "ordered"


@pytest.mark.parametrize("count", [2, 3, 8])
def test_links_and_only_entry_binds_interface(count):
    items = profiles(count)
    before = copy.deepcopy(items)
    built = chains.build(chains.resolve(chain_for(items), items))
    assert [o["tag"] for o in built] == [*(f"chain-{n}" for n in range(1, count)), "proxy"]
    for n, outbound in enumerate(built):
        expected = outbounds.build(items[n], outbound["tag"])
        if n:
            expected["streamSettings"]["sockopt"] = {"dialerProxy": f"chain-{n}"}
        assert outbound == expected
    assert items == before


@pytest.mark.parametrize("raw", [False, True])
def test_render_pins_entry_dns_and_keeps_explicit_exits_standalone(raw):
    items = profiles()
    dns = copy.deepcopy(settings.DEFAULTS["dns"])
    dns["remote_via_tunnel"] = True
    if raw:
        dns["raw_override"] = '{"servers":["1.1.1.1"],"hosts":{"kept.example":"192.0.2.8"}}'
    cfg = json.loads(render.build_text(
        chains.resolve(chain_for(items), items), "eth9", TEMPLATE,
        dns_cfg=dns, server_ip="192.0.2.10", exits=[Exit("standalone", items[-1])],
        exits_cfg={"port": 19090, "password": "test"}))
    by_tag = {o["tag"]: o for o in cfg["outbounds"]}
    assert cfg["outbounds"][0]["tag"] == "proxy"
    assert cfg["dns"]["hosts"][items[0].address] == "192.0.2.10"
    entry = next(o for o in cfg["outbounds"] if o["tag"] == "chain-1")
    assert entry["streamSettings"]["sockopt"]["domainStrategy"] == "ForceIPv4"
    assert items[-1].address not in cfg["dns"]["hosts"]
    if raw:
        assert cfg["dns"]["hosts"]["kept.example"] == "192.0.2.8"
    assert by_tag["chain-1"]["streamSettings"]["sockopt"]["interface"] == "eth9"
    assert by_tag["proxy"]["streamSettings"]["sockopt"] == {"dialerProxy": "chain-2"}
    assert by_tag["exit-hop-2"]["streamSettings"]["sockopt"] == {"interface": "eth9"}
    assert any(r.get("user") == ["standalone"] and r["outboundTag"] == "exit-hop-2"
               for r in cfg["routing"]["rules"])


def test_core_options_apply_per_hop_without_changing_links():
    items = profiles()
    items[0].security = items[1].security = "tls"
    items[1].fp = "firefox"
    core = {"fragment": {"enabled": True}, "default_fp": "chrome",
            "sockopt": {"tcp_fast_open": True}}
    built = chains.build(chains.resolve(chain_for(items), items), core)
    assert built[0]["streamSettings"]["tlsSettings"]["fingerprint"] == "chrome"
    assert built[1]["streamSettings"]["tlsSettings"]["fingerprint"] == "firefox"
    assert built[0]["streamSettings"]["finalmask"]["tcp"]
    assert built[0]["streamSettings"]["sockopt"]["tcpFastOpen"] is True
    for outbound in built[1:]:
        assert "finalmask" not in outbound["streamSettings"]
        assert "tcpFastOpen" not in outbound["streamSettings"]["sockopt"]


def test_mux_is_rejected_before_render():
    items = profiles()
    with pytest.raises(ValueError, match="[Mm]ux"):
        render.build_text(chains.resolve(chain_for(items), items), "eth0", TEMPLATE,
                          core_cfg={"mux": {"enabled": True}})


def test_existing_tag_collision_is_rejected(tmp_path):
    template = json.loads(TEMPLATE.read_text())
    template["outbounds"].append({"tag": "chain-1", "protocol": "freedom"})
    path = tmp_path / "template.json"
    path.write_text(json.dumps(template))
    items = profiles()
    with pytest.raises(ValueError, match="chain-1"):
        render.build_text(chains.resolve(chain_for(items), items), "eth0", path)


def test_chains_survive_backup_and_restore(monkeypatch, tmp_path):
    base = tmp_path / "data"
    monkeypatch.setattr(paths, "base_dir", lambda: base)
    monkeypatch.setattr(paths, "profiles_dir", lambda: base / "profiles")
    monkeypatch.setattr(backup, "_real_user_ids", lambda: None)
    store = chains.ChainStore()
    chain = chain_for(profiles())
    store.save(chain)
    archive = tmp_path / "backup.zip"
    backup.backup(archive)
    store.delete(chain.uid)
    backup.restore(archive)
    assert chains.ChainStore().get(chain.uid) == chain


def test_old_backup_clears_unrestored_chains(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    monkeypatch.setattr(backup, "_real_user_ids", lambda: None)
    archive = tmp_path / "old.zip"
    backup.backup(archive)
    chains.ChainStore().save(chain_for(profiles()))
    backup.restore(archive)
    assert chains.ChainStore().list() == []


@pytest.mark.parametrize("dns", [None, {"raw_override": '{"hosts":{"hop0.example":"192.0.2.99"}}'}])
def test_chain_entry_pin_matches_route_even_without_dns_settings_or_with_override(dns):
    items = profiles()
    cfg = json.loads(render.build_text(chains.resolve(chain_for(items), items), "eth0", TEMPLATE,
                                       dns_cfg=dns, server_ip="192.0.2.10"))
    assert cfg["dns"]["hosts"][items[0].address] == "192.0.2.10"
    entry = next(o for o in cfg["outbounds"] if o["tag"] == "chain-1")
    assert entry["streamSettings"]["sockopt"]["domainStrategy"] == "ForceIPv4"


def test_security_and_transport_settings_survive_chaining():
    items = profiles()
    items[0].security = "tls"
    items[0].sni = "entry-sni.example"
    items[1].security = "reality"
    items[1].sni = "middle-sni.example"
    items[1].pbk = "public-key"
    items[1].sid = "abcd"
    items[2].network = "httpupgrade"
    items[2].host = "exit-host.example"
    items[2].path = "/upgrade"
    built = chains.build(chains.resolve(chain_for(items), items))
    for index, outbound in enumerate(built):
        expected = outbounds.build(items[index], outbound["tag"])
        expected["streamSettings"].pop("sockopt")
        outbound["streamSettings"].pop("sockopt")
        assert outbound == expected


def test_subscription_refresh_and_removal_keep_chain_references(monkeypatch, tmp_path):
    from xrayui.core import subscription
    from xrayui.core.profiles import ProfileStore

    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    items = profiles(2)
    store = ProfileStore()
    for profile in items:
        store.save(profile)
    chain = chain_for(items)
    chains.ChainStore().save(chain)
    sub = subscription.Subscription(profile_uids=[p.uid for p in items])
    refreshed = [Profile.from_dict(p.to_dict()) for p in items]
    for n, p in enumerate(refreshed):
        p.uid = f"new-{n}"
        p.name = f"Renamed {n}"
    monkeypatch.setattr(subscription, "fetch", lambda *a, **k: (subscription.Usage(), refreshed))
    subscription.refresh(sub, store, subscription.SubscriptionStore())
    saved = chains.ChainStore().get(chain.uid)
    assert chains.validate(saved, store.list()) == []
    assert chains.resolve(saved, store.list()).entry.name == "Renamed 0"
    refreshed.pop()
    subscription.refresh(sub, store, subscription.SubscriptionStore())
    assert saved.hops == chain.hops
    assert "hop-1" in " ".join(chains.validate(saved, store.list()))
