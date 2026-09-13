"""Build Xray routing rules from bypass settings.

Two modes share one settings["routing"] dict:
- "simple" (default): the flat toggles below, unchanged from before rule
  sets existed. Traffic with no matching rule falls through to the first
  outbound ("proxy"), so only "direct"/"block" need rules.
- a custom rule set (routing["mode"] == a routing["sets"][i]["id"]): the
  set's own rules, converted the way v2rayN's GenRoutingUserRule does
  (see convert_user_rule). low_usage still applies in this mode too, as
  a direct rule ahead of the set's own rules, since a custom set has no
  idea what "low usage" means on its own.

Country and low-usage bypass use geosite/geoip categories from the bundled
Loyalsoldier data (ir/ru/cn, category-ads-all, private, win-spy/update/extra).
"""
from __future__ import annotations

import ipaddress
import re

# geosite/geoip category groups per country. First entry is domains, second IPs.
# The bare `domain:<tld>` entries also catch national domains the curated
# geosite lists miss (category-ir alone covers only a couple hundred).
COUNTRY_RULES: dict[str, tuple[list[str], list[str]]] = {
    "iran": (["geosite:category-ir", "domain:ir"], ["geoip:ir"]),
    "russia": (["geosite:category-ru", "domain:ru", "domain:su"], ["geoip:ru"]),
    "china": (["geosite:cn", "geosite:geolocation-cn", "domain:cn"], ["geoip:cn"]),
}

# Windows telemetry/update/background. geosite:win-* come from Loyalsoldier data;
# the explicit domains are a fallback if plain upstream data is bundled instead.
LOW_USAGE_CATEGORIES = ["geosite:win-spy", "geosite:win-update", "geosite:win-extra"]
LOW_USAGE_DOMAINS: list[str] = [
    "domain:telemetry.microsoft.com",
    "domain:vortex.data.microsoft.com",
    "domain:watson.telemetry.microsoft.com",
    "domain:settings-win.data.microsoft.com",
    "domain:events.data.microsoft.com",
    "domain:events.data.msn.com",
    "domain:windowsupdate.com",
    "domain:update.microsoft.com",
    "domain:delivery.mp.microsoft.com",
    "domain:dl.delivery.mp.microsoft.com",
    "domain:ctldl.windowsupdate.com",
    "domain:nexus.officeapps.live.com",
    "domain:nexusrules.officeapps.live.com",
]

_PREFIXES = ("domain:", "full:", "geosite:", "regexp:", "keyword:", "ext:")

DOMAIN_STRATEGIES = ("AsIs", "IPIfNonMatch", "IPOnDemand")

_OUTBOUNDS = ("proxy", "direct", "block")
_PORT_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")
_NETWORKS = ("tcp", "udp", "tcp,udp")


def _norm_domain(d: str) -> str:
    d = d.strip()
    return d if d.startswith(_PREFIXES) else f"domain:{d}"


def _simple_rules(r: dict) -> list[dict]:
    rules: list[dict] = []

    if r.get("block_ads"):
        rules.append({"type": "field", "domain": ["geosite:category-ads-all"],
                      "outboundTag": "block"})

    direct_domains: list[str] = []
    direct_ips: list[str] = []

    if r.get("direct_private", True):
        direct_domains.append("geosite:private")
        direct_ips.append("geoip:private")
    for country, key in (("iran", "direct_iran"), ("russia", "direct_russia"),
                         ("china", "direct_china")):
        if r.get(key):
            domains, ips = COUNTRY_RULES[country]
            direct_domains.extend(domains)
            direct_ips.extend(ips)
    if r.get("low_usage"):
        direct_domains.extend(LOW_USAGE_CATEGORIES)
        direct_domains.extend(LOW_USAGE_DOMAINS)
    direct_domains.extend(_norm_domain(d) for d in r.get("bypass_domains", []) if d.strip())
    direct_ips.extend(ip.strip() for ip in r.get("bypass_ips", []) if ip.strip())

    if direct_domains:
        rules.append({"type": "field", "domain": direct_domains, "outboundTag": "direct"})
    if direct_ips:
        rules.append({"type": "field", "ip": direct_ips, "outboundTag": "direct"})

    proxy_domains = [_norm_domain(d) for d in r.get("proxy_domains", []) if d.strip()]
    if proxy_domains:
        rules.append({"type": "field", "domain": proxy_domains, "outboundTag": "proxy"})

    return rules


def find_set(r: dict, set_id: str) -> dict | None:
    for s in r.get("sets") or []:
        if isinstance(s, dict) and s.get("id") == set_id:
            return s
    return None


def active_set(r: dict) -> dict | None:
    """The custom set routing["mode"] names, or None in simple mode."""
    mode = r.get("mode") or "simple"
    if mode == "simple":
        return None
    return find_set(r, mode)


def domain_strategy_for(r: dict) -> str:
    custom = active_set(r)
    strategy = (custom or {}).get("domain_strategy") or r.get("domain_strategy")
    return strategy if strategy in DOMAIN_STRATEGIES else "IPIfNonMatch"


def _coerce_str(value) -> str:
    """Anything a hand-edited or imported JSON might put in a string field.

    Notably: an int (a port typed as a JSON number, not a string) coerces;
    anything else that isn't already a string (a list, a dict, None) can't
    be meaningfully turned into one, so it becomes empty rather than
    crashing whatever calls .strip() on the result next.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""


def _coerce_str_list(value) -> list[str]:
    """A list field given as a bare string becomes a one-item list (a
    common hand-editing mistake); non-string entries are dropped rather
    than iterated character-by-character or crashing on .strip()."""
    if isinstance(value, str):
        value = [value]
    elif not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]


def _sanitize_port(port) -> str:
    port = _coerce_str(port).strip()
    return port if _PORT_RE.match(port) else ""


def _sanitize_network(network) -> str:
    network = _coerce_str(network).strip()
    return network if network in _NETWORKS else ""


def _sanitize_ip(ip) -> str | None:
    if not isinstance(ip, str) or not ip.strip():
        return None
    ip = ip.strip()
    if ip.startswith(("geoip:", "ext:")):
        return ip
    try:
        ipaddress.ip_network(ip, strict=False)
    except ValueError:
        return None
    return ip


def convert_user_rule(rule: dict) -> list[dict]:
    """One custom rule -> zero or more Xray field rules.

    Matches v2rayN's GenRoutingUserRule (ServiceLib/Services/CoreConfig/V2ray/
    V2rayRoutingService.cs): Xray ANDs every field inside one rule, so
    domain+ip in a single rule would almost never match both at once --
    split them into separate rules instead, each still carrying
    port/network/protocol. A rule with only port/network/protocol (no
    domain/ip/process) is emitted as-is. A bad field is dropped, not the
    whole rule: a bad rule must never stop Xray from starting.
    """
    if not rule.get("enabled", True):
        return []
    outbound = rule.get("outbound", "proxy")
    if outbound not in _OUTBOUNDS:
        return []

    port = _sanitize_port(rule.get("port", ""))
    network = _sanitize_network(rule.get("network", ""))
    protocol = _coerce_str_list(rule.get("protocol"))
    process = _coerce_str_list(rule.get("process"))

    domains = []
    for d in _coerce_str_list(rule.get("domain")):
        d = d.replace("<COMMA>", ",").strip()
        if d and not d.startswith("#"):
            domains.append(_norm_domain(d))

    ips = [ip for ip in (_sanitize_ip(x) for x in _coerce_str_list(rule.get("ip"))) if ip]

    def base() -> dict:
        out: dict = {"type": "field", "outboundTag": outbound}
        if port:
            out["port"] = port
        if network:
            out["network"] = network
        if protocol:
            out["protocol"] = protocol
        return out

    out_rules: list[dict] = []
    if domains:
        r = base()
        r["domain"] = domains
        out_rules.append(r)
    if ips:
        r = base()
        r["ip"] = ips
        out_rules.append(r)
    if process:
        r = base()
        r["process"] = process
        out_rules.append(r)
    if not out_rules and (port or network or protocol):
        out_rules.append(base())
    return out_rules


def build_rules(r: dict) -> list[dict]:
    mode = r.get("mode") or "simple"
    if mode == "simple":
        return _simple_rules(r)

    custom = find_set(r, mode)
    if custom is None:
        return _simple_rules(r)  # unknown/missing set id: fall back, never raise

    rules: list[dict] = []
    if r.get("low_usage"):
        domains = list(LOW_USAGE_CATEGORIES) + list(LOW_USAGE_DOMAINS)
        rules.append({"type": "field", "domain": domains, "outboundTag": "direct"})
    for rule in custom.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        try:
            rules.extend(convert_user_rule(rule))
        except Exception:
            # Belt-and-suspenders on top of convert_user_rule's own field
            # sanitizing: hand-edited or imported JSON can still hold a
            # shape neither of us anticipated, and one bad rule must never
            # stop the rest of the set -- let alone Xray itself -- from
            # working.
            continue
    return rules


def has_custom_routing(r: dict) -> bool:
    return bool(build_rules(r))


def direct_domains(rules: list[dict]) -> list[str]:
    """The ordered, de-duplicated "domain" entries of every direct rule in
    build_rules()'s output -- works in both simple and custom modes, since
    it reads the already-built Xray rules rather than the raw settings.
    Used to scope the domestic DNS server to only the sites that actually
    go direct.
    """
    seen: set[str] = set()
    out: list[str] = []
    for rule in rules:
        if rule.get("outboundTag") != "direct":
            continue
        for d in rule.get("domain") or []:
            if d not in seen:
                seen.add(d)
                out.append(d)
    return out


def all_possible_rules(r: dict) -> list[dict]:
    """Every rule any mode -- simple, or any saved set -- could produce.

    Used to validate a candidate geo data source before it's swapped in:
    only checking the currently-active mode would let someone switch to a
    different set later and immediately hit a geo category the new data
    never had.
    """
    rules = list(_simple_rules(r))
    for s in r.get("sets") or []:
        if not isinstance(s, dict):
            continue
        for rule in s.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            try:
                rules.extend(convert_user_rule(rule))
            except Exception:
                continue
    return rules
