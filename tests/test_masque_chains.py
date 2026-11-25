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
    conn = _conn(monkeypatch)
    p = Profile(protocol="masque", address="1.2.3.4", port=443,
                username="user", id="")
    with pytest.raises(_Halt):
        conn.connect(p)


def test_masque_profile_without_address_still_rejected(monkeypatch):
    conn = _conn(monkeypatch)
    p = Profile(protocol="masque", address="", port=443, username="user")
    with pytest.raises(connection.ConnectError, match="missing address or id"):
        conn.connect(p)


def test_non_masque_protocol_without_id_still_rejected(monkeypatch):
    conn = _conn(monkeypatch)
    p = Profile(protocol="vless", address="1.2.3.4", port=443, id="")
    with pytest.raises(connection.ConnectError, match="missing address or id"):
        conn.connect(p)


def test_masque_not_yet_accepted_for_chains():
    # MASQUE is not in SUPPORTED_PROTOCOLS yet, so a chain hop with it is
    # rejected rather than silently accepted.
    entry = Profile(uid="m1", protocol="masque", address="1.2.3.4", port=443,
                    username="user")
    exit_ = Profile(uid="v1", protocol="vless", address="2.3.4.5", port=443,
                    id="11111111-1111-1111-1111-111111111111")
    chain = chains.Chain(uid="c1", hops=["m1", "v1"])
    problems = chains.validate(chain, {p.uid: p for p in (entry, exit_)})
    assert any("not verified for chains" in x for x in problems)


# -- coreopts: h2 vs h3, no mux ----------------------------------------------
def test_masque_never_mux_eligible():
    assert coreopts.mux_eligible(_profile(protocol="masque", alpn="h2")) is False
    assert coreopts.mux_eligible(_profile(protocol="masque", alpn="h3")) is False


def test_masque_fragment_only_for_h2():
    assert coreopts.fragment_eligible(_profile(protocol="masque", alpn="h2")) is True
    assert coreopts.fragment_eligible(_profile(protocol="masque", alpn="h3")) is False
    # alpn empty defaults to h2 (the single carrier).
    assert coreopts.fragment_eligible(_profile(protocol="masque", alpn="")) is True


def test_masque_sockopt_only_for_h2():
    assert coreopts.sockopt_eligible(_profile(protocol="masque", alpn="h2")) is True
    assert coreopts.sockopt_eligible(_profile(protocol="masque", alpn="h3")) is False


def test_masque_fragment_not_applied_for_h3():
    out = _render(_profile(protocol="masque", alpn="h3"),
                  core_cfg=_core(fragment={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert not (proxy.get("streamSettings", {}).get("finalmask", {}).get("tcp"))


def test_masque_fragment_applied_for_h2():
    out = _render(_profile(protocol="masque", alpn="h2"),
                  core_cfg=_core(fragment={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert proxy["streamSettings"]["finalmask"]["tcp"]


def test_masque_mux_not_applied_when_enabled():
    out = _render(_profile(protocol="masque", alpn="h2"),
                  core_cfg=_core(mux={"enabled": True}))
    proxy = next(o for o in out["outbounds"] if o["tag"] == "proxy")
    assert "mux" not in proxy
