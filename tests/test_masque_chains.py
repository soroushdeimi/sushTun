"""MASQUE chain/connection validation: id exemption and unsupported combos.

OS interactions are mocked; no real network, routes, DNS or TUN.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from xrayui.core import chains, connection, coreopts, render
from xrayui.core import settings as app_settings
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


def _core(**over) -> dict:
    d = copy.deepcopy(app_settings.DEFAULTS["core"])
    d.update(over)
    return d


def _profile(**over) -> Profile:
    base = dict(name="p", protocol="vless", address="a.example.com", port=443,
                id="11111111-1111-1111-1111-111111111111", encryption="none",
                network="tcp", security="tls", sni="a.example.com")
    base.update(over)
    return Profile(**base)


def _render(profile=None, **kw):
    return json.loads(render.build_text(profile or _profile(), "lo", TEMPLATE, **kw))


class _Halt(Exception):
    pass


def _conn(monkeypatch):
    class DummyState:
        def is_connected(self):
            return False

        def pending(self):
            return {}

    conn = connection.Connection()
    conn.state = DummyState()
    monkeypatch.setattr(
        conn, "_drain_pending_dns",
        lambda *a, **kw: (_ for _ in ()).throw(_Halt))
    return conn


def test_masque_profile_without_id_passes_id_check(monkeypatch):
    # MASQUE authenticates with basic auth / WARP identity, not a VLESS id.
    # A complete WARP identity is a valid MASQUE profile with no `id`. The
    # keys use syntactically valid dummy base64 and a /32 host prefix so the
    # profile stays valid under the stricter shared builder.
    conn = _conn(monkeypatch)
    p = Profile(protocol="masque", address="1.2.3.4", port=443,
                security="tls",
                masque_private_key="AQID", masque_public_key="BAUG",
                masque_addresses="10.0.0.1/32")
    with pytest.raises(_Halt):
        conn.connect(p)


def test_masque_invalid_identity_fails_closed_before_interface(monkeypatch):
    # A MASQUE profile that fails model validation (basic auth must be
    # both-or-neither) is rejected BEFORE any interface/state/DNS mutation:
    # the mocked _drain_pending_dns (which would raise _Halt) is never reached.
    conn = _conn(monkeypatch)
    p = Profile(protocol="masque", address="1.2.3.4", port=443,
                security="tls", username="user", id="")
    with pytest.raises(connection.ConnectError,
                       match="invalid TLS or credential settings"):
        conn.connect(p)


def test_masque_profile_without_address_still_rejected(monkeypatch):
    conn = _conn(monkeypatch)
    p = Profile(protocol="masque", address="", port=443,
                security="tls", username="user", id="pass")
    with pytest.raises(connection.ConnectError, match="missing address or id"):
        conn.connect(p)


def test_non_masque_protocol_without_id_still_rejected(monkeypatch):
    conn = _conn(monkeypatch)
    p = Profile(protocol="vless", address="1.2.3.4", port=443, id="")
    with pytest.raises(connection.ConnectError, match="missing address or id"):
        conn.connect(p)


def _masque_entry(**over) -> Profile:
    base = dict(uid="m1", protocol="masque", address="1.2.3.4", port=443,
                security="tls", username="user", id="pass",
                masque_http_version="h2")
    base.update(over)
    return Profile(**base)


def _vless(**over) -> Profile:
    base = dict(uid="v1", protocol="vless", address="2.3.4.5", port=443,
                id="11111111-1111-1111-1111-111111111111")
    base.update(over)
    return Profile(**base)


def test_masque_accepted_as_h2_entry():
    entry = _masque_entry()
    exit_ = _vless()
    chain = chains.Chain(uid="c1", hops=["m1", "v1"])
    assert chains.validate(chain, {p.uid: p for p in (entry, exit_)}) == []


def test_masque_rejected_as_exit():
    entry = _vless()
    exit_ = _masque_entry(uid="m2")
    chain = chains.Chain(uid="c1", hops=["v1", "m2"])
    problems = chains.validate(chain, {p.uid: p for p in (entry, exit_)})
    assert any("only verified as the first hop" in x for x in problems)


def test_masque_rejected_as_middle_hop():
    entry = _vless()
    middle = _masque_entry(uid="m2")
    exit_ = _vless(uid="v2")
    chain = chains.Chain(uid="c1", hops=["v1", "m2", "v2"])
    problems = chains.validate(chain, {p.uid: p for p in (entry, middle, exit_)})
    assert any("only verified as the first hop" in x for x in problems)


def test_masque_h3_entry_rejected_until_proven():
    entry = _masque_entry(masque_http_version="h3")
    exit_ = _vless()
    chain = chains.Chain(uid="c1", hops=["m1", "v1"])
    problems = chains.validate(chain, {p.uid: p for p in (entry, exit_)})
    assert any("H3" in x and "not verified" in x for x in problems)


def test_masque_entry_invalid_identity_rejected():
    # basic auth must be both-or-neither; a username without a pass is invalid.
    entry = _masque_entry(id="")
    exit_ = _vless()
    chain = chains.Chain(uid="c1", hops=["m1", "v1"])
    problems = chains.validate(chain, {p.uid: p for p in (entry, exit_)})
    assert any("missing an address or credential" in x for x in problems)


def test_masque_h2_chain_renders_through_shared_model():
    # Real render.build_text(include_tun=False) over the shared model: the
    # MASQUE entry is built by outbounds.build and the exit dials through it.
    entry = _masque_entry()
    exit_ = _vless()
    plan = chains.resolve(chains.Chain(uid="c1", name="c", hops=["m1", "v1"]),
                          {p.uid: p for p in (entry, exit_)})
    out = json.loads(render.build_text(plan, "lo", TEMPLATE, include_tun=False))
    tags = {o["tag"]: o for o in out["outbounds"]}
    assert tags["chain-1"]["protocol"] == "masque"
    assert tags["chain-1"]["streamSettings"]["network"] == "masque"
    assert tags["chain-1"]["streamSettings"]["tlsSettings"]["alpn"] == ["h2"]
    assert tags["proxy"]["protocol"] == "vless"
    assert tags["proxy"]["streamSettings"]["sockopt"] == {"dialerProxy": "chain-1"}
    # The entry owns the physical interface binding.
    assert tags["chain-1"]["streamSettings"]["sockopt"]["interface"] == "lo"
    # No TUN inbound is rendered.
    assert not any(i.get("tag") == "tun-in" for i in out["inbounds"])


def test_masque_h3_chain_rejected_by_render():
    # H3 chains are not verified yet, so resolve/render must fail closed.
    entry = _masque_entry(masque_http_version="h3")
    exit_ = _vless()
    with pytest.raises(ValueError, match="H3"):
        chains.resolve(chains.Chain(uid="c1", name="c", hops=["m1", "v1"]),
                       {p.uid: p for p in (entry, exit_)})


# -- coreopts: h2 vs h3, no mux ----------------------------------------------
def test_masque_never_mux_eligible():
    assert coreopts.mux_eligible(_profile(protocol="masque",
                                          masque_http_version="h2")) is False
    assert coreopts.mux_eligible(_profile(protocol="masque",
                                          masque_http_version="h3")) is False


def test_masque_fragment_only_for_h2():
    assert coreopts.fragment_eligible(_profile(protocol="masque",
                                               masque_http_version="h2")) is True
    assert coreopts.fragment_eligible(_profile(protocol="masque",
                                               masque_http_version="h3")) is False
    # empty masque_http_version defaults to h2 (the single carrier).
    assert coreopts.fragment_eligible(_profile(protocol="masque",
                                               masque_http_version="")) is True


def test_masque_sockopt_only_for_h2():
    assert coreopts.sockopt_eligible(_profile(protocol="masque",
                                              masque_http_version="h2")) is True
    assert coreopts.sockopt_eligible(_profile(protocol="masque",
                                              masque_http_version="h3")) is False


def test_masque_carrier_ignores_contradictory_alpn():
    # Imported/share-created profiles may carry an empty or contradictory
    # alpn; masque_http_version is authoritative.
    p = _profile(protocol="masque", masque_http_version="h3", alpn="h2")
    assert coreopts.fragment_eligible(p) is False
    assert coreopts.sockopt_eligible(p) is False
    p = _profile(protocol="masque", masque_http_version="h2", alpn="h3")
    assert coreopts.fragment_eligible(p) is True
    assert coreopts.sockopt_eligible(p) is True
    p = _profile(protocol="masque", masque_http_version="h3", alpn="")
    assert coreopts.fragment_eligible(p) is False
    assert coreopts.sockopt_eligible(p) is False


def test_masque_fragment_not_applied_for_h3():
    out = _render(_profile(protocol="masque", masque_http_version="h3"),
                  core_cfg=_core(fragment={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert not (proxy.get("streamSettings", {}).get("finalmask", {}).get("tcp"))


def test_masque_fragment_applied_for_h2():
    out = _render(_profile(protocol="masque", masque_http_version="h2"),
                  core_cfg=_core(fragment={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert proxy["streamSettings"]["finalmask"]["tcp"]


def test_masque_fragment_not_applied_for_h3_with_contradictory_alpn():
    out = _render(_profile(protocol="masque", masque_http_version="h3", alpn="h2"),
                  core_cfg=_core(fragment={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert not (proxy.get("streamSettings", {}).get("finalmask", {}).get("tcp"))


def test_masque_mux_not_applied_when_enabled():
    out = _render(_profile(protocol="masque", masque_http_version="h2"),
                  core_cfg=_core(mux={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert "mux" not in proxy
