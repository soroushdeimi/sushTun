"""Build Xray routing rules from bypass settings.

Traffic with no matching rule falls through to the first outbound ("proxy"),
so we only emit rules for what should go "direct" (bypass the tunnel) or "block".
Country and low-usage bypass use geosite/geoip categories from the bundled
Loyalsoldier data (ir/ru/cn, category-ads-all, private, win-spy/update/extra).
"""
from __future__ import annotations

# geosite/geoip category groups per country. First entry is domains, second IPs.
COUNTRY_RULES: dict[str, tuple[list[str], list[str]]] = {
    "iran": (["geosite:category-ir"], ["geoip:ir"]),
    "russia": (["geosite:category-ru"], ["geoip:ru"]),
    "china": (["geosite:cn", "geosite:geolocation-cn"], ["geoip:cn"]),
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

# Convenience presets: domestic services people commonly bypass. The country
# toggles above already cover most of these in bulk.
APP_PRESETS: dict[str, list[str]] = {
    "Aparat": ["domain:aparat.com"],
    "Digikala": ["domain:digikala.com"],
    "Divar": ["domain:divar.ir"],
    "Iranian banks": ["domain:shaparak.ir", "domain:sadad.ir", "domain:bmi.ir"],
}

_PREFIXES = ("domain:", "full:", "geosite:", "regexp:", "keyword:", "ext:")


def _norm_domain(d: str) -> str:
    d = d.strip()
    return d if d.startswith(_PREFIXES) else f"domain:{d}"


def build_rules(r: dict) -> list[dict]:
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
    for name in r.get("app_presets", []):
        direct_domains.extend(APP_PRESETS.get(name, []))
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


def has_custom_routing(r: dict) -> bool:
    return bool(build_rules(r))
