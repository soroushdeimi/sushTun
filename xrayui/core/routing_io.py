"""Import/export routing rule sets in v2rayN-compatible JSON shapes.

v2rayN is GPL-3.0 and sushTun is MIT, so nothing is copied from it here --
only the wire shapes (field names v2rayN's RulesItem/RoutingItem/
RoutingTemplate use) are matched, for interop with rule sets already
published in that format (e.g. Chocolate4U's Iran rules).
"""
from __future__ import annotations

import json
import urllib.request
import uuid
from collections.abc import Callable

from . import subscription

_UA = subscription._UA  # same v2rayNG UA subscription.py already uses

_OUTBOUNDS = ("proxy", "direct", "block")

Fetch = Callable[[str], str]


def _ci_get(d: dict, *names: str, default=None):
    """Case-insensitive lookup: v2rayN writes "Remarks"/"RuleSet" in
    templates but "remarks"/"outboundTag" in its rule samples."""
    lower = {k.lower(): v for k, v in d.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return default


def _rule_from_dict(d: dict) -> dict | None:
    outbound = _ci_get(d, "outboundTag", "outbound", default="proxy")
    if outbound not in _OUTBOUNDS:
        return None
    return {
        "remarks": _ci_get(d, "remarks", default="") or "",
        "enabled": bool(_ci_get(d, "enabled", default=True)),
        "outbound": outbound,
        "domain": list(_ci_get(d, "domain", default=[]) or []),
        "ip": list(_ci_get(d, "ip", default=[]) or []),
        "port": _ci_get(d, "port", default="") or "",
        "network": _ci_get(d, "network", default="") or "",
        "protocol": list(_ci_get(d, "protocol", default=[]) or []),
        "process": list(_ci_get(d, "process", default=[]) or []),
    }


def _rules_from_array(data: list) -> tuple[list[dict], int]:
    rules: list[dict] = []
    skipped = 0
    for item in data:
        rule = _rule_from_dict(item) if isinstance(item, dict) else None
        if rule is None:
            skipped += 1
        else:
            rules.append(rule)
    return rules, skipped


def _parse_ruleset_field(raw) -> list:
    # v2rayN's RoutingItem.RuleSet is typed as a C# string (a JSON-encoded
    # array), but a hand-edited or re-exported file may hold the array
    # directly -- accept either.
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except ValueError:
            return []
        return data if isinstance(data, list) else []
    return []


def _set_from_routing_item(item: dict, fetch: Fetch | None) -> tuple[dict, int] | None:
    name = _ci_get(item, "remarks", "name", default="Imported") or "Imported"
    domain_strategy = _ci_get(item, "domainStrategy", "domain_strategy", default="") or ""
    ruleset_raw = _ci_get(item, "ruleSet", default=None)
    url = _ci_get(item, "url", default="") or ""

    if ruleset_raw is None and url:
        if fetch is None:
            return None
        try:
            data = json.loads(fetch(url))
        except (ValueError, OSError):
            return None
    else:
        data = _parse_ruleset_field(ruleset_raw)

    if not isinstance(data, list):
        return None

    rules, skipped = _rules_from_array(data)
    rule_set = {
        "id": uuid.uuid4().hex,
        "name": name,
        "domain_strategy": domain_strategy,
        "rules": rules,
    }
    return rule_set, skipped


def import_rules(text: str, fetch: Fetch | None = None) -> tuple[list[dict], int]:
    """Parse any of the three v2rayN-compatible shapes.

    Returns (sets, skipped_count): a list of new rule sets (each with a
    fresh id, ready to append to settings["routing"]["sets"]) plus how many
    rules across all of them had an outboundTag this app doesn't support
    and were dropped, for the caller to show the user.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return [], 0

    if isinstance(data, list):
        rules, skipped = _rules_from_array(data)
        if not rules:
            return [], skipped
        return [{"id": uuid.uuid4().hex, "name": "Imported",
                 "domain_strategy": "", "rules": rules}], skipped

    if isinstance(data, dict):
        items = _ci_get(data, "routingItems", default=None)
        if isinstance(items, list):
            sets: list[dict] = []
            total_skipped = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                result = _set_from_routing_item(item, fetch)
                if result is None:
                    continue
                rule_set, skipped = result
                sets.append(rule_set)
                total_skipped += skipped
            return sets, total_skipped

        result = _set_from_routing_item(data, fetch)
        if result is None:
            return [], 0
        rule_set, skipped = result
        return [rule_set], skipped

    return [], 0


def _default_fetch(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (user-provided URL)
        return resp.read().decode("utf-8", errors="replace")


def import_url(url: str, fetch: Fetch | None = None) -> tuple[list[dict], int]:
    fetch = fetch or _default_fetch
    return import_rules(fetch(url), fetch=fetch)


def export_rules(rule_set: dict) -> list[dict]:
    """A rule set's rules as a bare array, in v2rayN's own sample key style."""
    out = []
    for rule in rule_set.get("rules") or []:
        item: dict = {
            "remarks": rule.get("remarks", ""),
            "outboundTag": rule.get("outbound", "proxy"),
            "enabled": rule.get("enabled", True),
        }
        for key, src in (("domain", "domain"), ("ip", "ip"), ("protocol", "protocol"),
                         ("process", "process")):
            if rule.get(src):
                item[key] = list(rule[src])
        if rule.get("port"):
            item["port"] = rule["port"]
        if rule.get("network"):
            item["network"] = rule["network"]
        out.append(item)
    return out
