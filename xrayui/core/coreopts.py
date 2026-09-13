"""settings["core"] -> Xray config overlays: TLS fragment, mux, sniffing,
local proxy (socks-in) and a default TLS fingerprint.

Every knob here is opt-in. With every value at its default, every apply_*
function below is a no-op (sniffing's defaults already match the
template's own values), so an untouched install renders exactly what it
always has -- the same rule every other settings-driven overlay in this
app follows.
"""
from __future__ import annotations

import re

from .metrics import STATS_API_PORT
from .profiles import Profile

_PACKETS_RE = re.compile(r"^(tlshello|\d+(-\d+)?)$")
_RANGE_RE = re.compile(r"^\d+(-\d+)?$")
_MUX_ELIGIBLE_PROTOCOLS = frozenset({"vmess", "trojan", "shadowsocks"})
_XUDP_UDP443_VALUES = ("reject", "allow", "skip")
_DEFAULT_FP_VALUES = frozenset(
    {"chrome", "firefox", "safari", "edge", "ios", "android", "random", "randomized"}
)
DEFAULT_FP_CHOICES = ("chrome", "firefox", "safari", "edge", "ios", "android",
                      "random", "randomized")
DEFAULT_SOCKS_PORT = 10808


# -- TLS fragment -------------------------------------------------------------
def fragment_eligible(profile: Profile) -> bool:
    protocol = (profile.protocol or "").lower()
    if protocol in ("wireguard", "hysteria2"):
        return False
    return profile.security in ("tls", "reality")


def build_fragment_mask(cfg: dict) -> dict:
    """The fragment mask object. A bad field falls back to the documented
    default rather than failing the whole thing -- a typo in settings.json
    must not turn into "the app will not connect". Only "length"/"delay"
    (the legacy singular keys) are emitted: confirmed against a real xray
    26.3.27 binary that the plural "lengths"/"delays" arrays alone are NOT
    parsed by this version ('LengthMin can't be 0') even though the fields
    exist in the struct; only the legacy singular strings actually work.
    """
    packets = str(cfg.get("packets") or "").strip()
    if not _PACKETS_RE.match(packets):
        packets = "tlshello"
    length = str(cfg.get("length") or "").strip()
    if not _RANGE_RE.match(length):
        length = "100-200"
    interval = str(cfg.get("interval") or "").strip()
    if not _RANGE_RE.match(interval):
        interval = "10-20"
    max_split = cfg.get("max_split")
    if isinstance(max_split, bool) or not isinstance(max_split, int) or not 0 <= max_split <= 10000:
        max_split = 0
    return {
        "type": "fragment",
        "settings": {
            "packets": packets,
            "length": length,
            "delay": interval,
            "maxSplit": max_split,
        },
    }


def apply_fragment(cfg: dict, core_cfg: dict, profile: Profile) -> None:
    fragment_cfg = core_cfg.get("fragment") or {}
    if not fragment_cfg.get("enabled") or not fragment_eligible(profile):
        return
    mask = build_fragment_mask(fragment_cfg)
    for outbound in cfg.get("outbounds", []):
        stream = outbound.get("streamSettings")
        if not stream or not stream.get("security"):
            continue
        # A dialerProxy chain means this outbound doesn't dial the network
        # itself; fragmenting it wouldn't fragment the actual TLS handshake.
        if (stream.get("sockopt") or {}).get("dialerProxy"):
            continue
        finalmask = stream.setdefault("finalmask", {})
        if finalmask.get("tcp"):
            continue  # something upstream already set one; do not stack
        finalmask["tcp"] = [mask]


# -- Mux ------------------------------------------------------------------
def mux_eligible(profile: Profile) -> bool:
    protocol = (profile.protocol or "").lower()
    if protocol in _MUX_ELIGIBLE_PROTOCOLS:
        return True
    # vless is mux-eligible only without a flow: XTLS Vision (the only flow
    # this app offers) multiplexes its own stream and breaks under mux.
    return protocol == "vless" and not profile.flow


def build_mux(cfg: dict) -> dict:
    concurrency = cfg.get("concurrency")
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or not 1 <= concurrency <= 1024:
        concurrency = 8
    xudp_concurrency = cfg.get("xudp_concurrency")
    if (isinstance(xudp_concurrency, bool) or not isinstance(xudp_concurrency, int)
            or not 1 <= xudp_concurrency <= 1024):
        xudp_concurrency = 16
    xudp_udp443 = str(cfg.get("xudp_proxy_udp443") or "").strip()
    if xudp_udp443 not in _XUDP_UDP443_VALUES:
        xudp_udp443 = "reject"
    return {
        "enabled": True,
        "concurrency": concurrency,
        "xudpConcurrency": xudp_concurrency,
        "xudpProxyUDP443": xudp_udp443,
    }


def apply_mux(cfg: dict, core_cfg: dict, profile: Profile) -> None:
    mux_cfg = core_cfg.get("mux") or {}
    if not mux_cfg.get("enabled") or not mux_eligible(profile):
        return
    proxy = next((o for o in cfg.get("outbounds", []) if o.get("tag") == "proxy"), None)
    if proxy is None:
        return
    proxy["mux"] = build_mux(mux_cfg)


# -- Sniffing ---------------------------------------------------------------
def apply_sniffing(cfg: dict, core_cfg: dict) -> None:
    sniffing_cfg = core_cfg.get("sniffing") or {}
    enabled = sniffing_cfg.get("enabled", True)
    route_only = bool(sniffing_cfg.get("route_only"))
    for inbound in cfg.get("inbounds", []):
        if inbound.get("tag") not in ("tun-in", "socks-in"):
            continue
        if not enabled:
            inbound.pop("sniffing", None)
            continue
        if route_only:
            inbound.setdefault("sniffing", {})["routeOnly"] = True


# -- Local proxy (socks-in) --------------------------------------------------
def valid_socks_port(port) -> int:
    if isinstance(port, bool) or not isinstance(port, int):
        return DEFAULT_SOCKS_PORT
    if port == STATS_API_PORT or not 1024 <= port <= 65535:
        return DEFAULT_SOCKS_PORT
    return port


def apply_local_proxy(cfg: dict, core_cfg: dict) -> int:
    """Overlay socks_port/allow_lan/auth onto socks-in. Returns the
    effective port so a caller (connection.py's macOS tun2socks bridge)
    uses the exact same validated value without redoing the validation."""
    port = valid_socks_port(core_cfg.get("socks_port"))
    socks_in = next((i for i in cfg.get("inbounds", []) if i.get("tag") == "socks-in"), None)
    if socks_in is None:
        return port
    socks_in["port"] = port
    if core_cfg.get("allow_lan"):
        socks_in["listen"] = "0.0.0.0"
        user = str(core_cfg.get("lan_user") or "").strip()
        pw = str(core_cfg.get("lan_pass") or "").strip()
        if user and pw:
            settings = socks_in.setdefault("settings", {})
            settings["auth"] = "password"
            settings["accounts"] = [{"user": user, "pass": pw}]
    return port


# -- Default TLS fingerprint --------------------------------------------------
def apply_default_fp(cfg: dict, core_cfg: dict, profile: Profile) -> None:
    if profile.fp:
        return  # the profile's own fingerprint always wins
    fp = str(core_cfg.get("default_fp") or "").strip()
    if fp not in _DEFAULT_FP_VALUES:
        return
    proxy = next((o for o in cfg.get("outbounds", []) if o.get("tag") == "proxy"), None)
    if proxy is None:
        return
    stream = proxy.get("streamSettings") or {}
    security = stream.get("security")
    if security == "tls":
        stream.setdefault("tlsSettings", {}).setdefault("fingerprint", fp)
    elif security == "reality":
        stream.setdefault("realitySettings", {}).setdefault("fingerprint", fp)


def apply_all(cfg: dict, core_cfg: dict, profile: Profile) -> None:
    """Everything render.build_text needs, in the order that keeps each
    step consistent with the ones after it (sniffing/local-proxy touch
    inbounds; fingerprint/fragment/mux touch the proxy outbound, in an
    order where mux never sees -- and so never misinterprets -- a fragment
    mask, and fragment never wraps a fingerprint it should be independent
    of)."""
    apply_sniffing(cfg, core_cfg)
    apply_local_proxy(cfg, core_cfg)
    apply_default_fp(cfg, core_cfg, profile)
    apply_fragment(cfg, core_cfg, profile)
    apply_mux(cfg, core_cfg, profile)
