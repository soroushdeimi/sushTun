"""Per-protocol outbound builders, dispatched by Profile.protocol.

vless.apply is also the fallback for any protocol that isn't specially
handled, matching the pre-split behaviour where only wireguard branched off.
"""
from __future__ import annotations

from ..profiles import Profile
from . import hysteria2, shadowsocks, trojan, vless, vmess, wireguard

_BUILDERS = {
    "wireguard": wireguard.apply,
    "vmess": vmess.apply,
    "trojan": trojan.apply,
    "shadowsocks": shadowsocks.apply,
    "hysteria2": hysteria2.apply,
}


def _builder_for(p: Profile):
    return _BUILDERS.get((p.protocol or "").lower(), vless.apply)


def apply_profile(cfg: dict, p: Profile) -> None:
    proxy = next((o for o in cfg.get("outbounds", []) if o.get("tag") == "proxy"), None)
    if proxy is None:
        raise ValueError("template has no outbound tagged 'proxy'")
    _builder_for(p)(proxy, p)


def build(p: Profile, tag: str) -> dict:
    """A standalone outbound dict for p, tagged `tag`.

    Used to build one-off outbounds outside config.template.json (the speed
    test builds a whole config from scratch, one outbound per profile).
    """
    proxy: dict = {"tag": tag}
    _builder_for(p)(proxy, p)
    return proxy
