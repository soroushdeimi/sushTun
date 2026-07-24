"""Build Xray routing rules from bypass settings.

Traffic with no matching rule falls through to the first outbound ("proxy"),
so we only emit rules for what should go "direct" (bypass the tunnel) or "block".
"""
from __future__ import annotations

# Windows telemetry / update / background chatter that just wastes quota.
LOW_USAGE_DOMAINS: list[str] = [
    "domain:telemetry.microsoft.com",
    "domain:vortex.data.microsoft.com",
    "domain:watson.telemetry.microsoft.com",
    "domain:settings-win.data.microsoft.com",
    "domain:events.data.microsoft.com",
    "domain:events.data.msn.com",
    "domain:watson.microsoft.com",
    "domain:oca.telemetry.microsoft.com",
    "domain:sqm.telemetry.microsoft.com",
    "domain:windowsupdate.com",
    "domain:update.microsoft.com",
    "domain:delivery.mp.microsoft.com",
    "domain:dl.delivery.mp.microsoft.com",
    "domain:emdl.ws.microsoft.com",
    "domain:ctldl.windowsupdate.com",
    "domain:nexus.officeapps.live.com",
    "domain:nexusrules.officeapps.live.com",
    "domain:msedge.api.cdp.microsoft.com",
    "domain:diagnostics.support.microsoft.com",
    "domain:browser.events.data.msn.com",
]

# Convenience presets: domestic services people commonly bypass. Enabling the
# "direct_iran" geosite toggle already covers most of these in bulk.
APP_PRESETS: dict[str, list[str]] = {
    "Aparat": ["domain:aparat.com"],
    "Digikala": ["domain:digikala.com"],
    "Divar": ["domain:divar.ir"],
    "Iranian banks": ["domain:shaparak.ir", "domain:sadad.ir", "domain:bmi.ir"],
}

_PREFIXES = ("domain:", "full:", "geosite:", "regexp:", "keyword:")


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
    if r.get("direct_iran"):
        direct_domains.append("geosite:category-ir")
        direct_ips.append("geoip:ir")
    if r.get("low_usage"):
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
