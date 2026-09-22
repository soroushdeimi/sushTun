"""Central app settings persisted to settings.json (deep-merged with defaults)."""
from __future__ import annotations

import copy
import json
from collections.abc import Callable

from .. import paths

LOG_LEVELS = ("debug", "info", "warning", "error", "none")

# Bump when DEFAULTS' shape changes, and add a migration below so an old
# settings.json keeps loading instead of silently losing data to _merge.
SCHEMA_VERSION = 1

DEFAULTS: dict = {
    "schema_version": SCHEMA_VERSION,
    "language": "en",
    "ping_target": "1.1.1.1",
    "sample_seconds": 5,
    "log_level": "warning",
    "tun_mtu": 1420,
    # Empty means "inherit the template", so an untouched install renders the
    # bundled config verbatim. See core/dns.py.
    # `hosts` is a list of "domain = address" lines, not a map: _merge treats a
    # dict as a schema and filters saved keys against it, so a map default of {}
    # would silently discard every entry. Lists are replaced wholesale.
    "dns": {
        "servers": [],
        "query_strategy": "",
        "hosts": [],
        # New keys below: all opt-in, so an untouched install renders exactly
        # what it always has. No migration needed -- see dns.build_dns_and_rules.
        "domestic_servers": [],
        "remote_via_tunnel": False,
        "parallel_query": False,
        "serve_stale": False,
        "raw_override": "",
        # Company / internal networks: `domain = DNS server IP` lines (dns.py).
        "internal": [],
    },
    "routing": {
        # The flat toggles below are "Simple" mode -- unreshaped, so no
        # migration is needed for them. "mode" is either "simple" or a
        # sets[i]["id"]; an id that no longer exists falls back to simple
        # (routing.build_rules never raises on a bad/missing mode).
        "low_usage": False,
        "block_ads": True,
        "direct_iran": True,
        "direct_russia": False,
        "direct_china": False,
        "direct_private": True,
        "bypass_domains": [],
        "bypass_ips": [],
        "proxy_domains": [],
        "mode": "simple",
        "domain_strategy": "IPIfNonMatch",
        # Each set: {id, name, domain_strategy, rules: [rule, ...]}. Each
        # rule: {remarks, enabled, outbound: proxy|direct|block, domain: [],
        # ip: [], port: "", network: "", protocol: [], process: []}. A list,
        # not a dict, so _merge replaces it wholesale like dns.hosts already
        # does -- routing.convert_user_rule sanitizes every field on its own
        # since nothing here validates the set's shape.
        "sets": [],
    },
    "gateway": {
        "enabled": False,
        "start_hotspot": True,
        # Linux hotspot. The password is generated on first use and kept, so a
        # phone that joined once rejoins on its own.
        "ssid": "sushTun",
        "password": "",
        # Linux hotspot options (Settings → Hotspot). These defaults start the
        # hotspot exactly as before: WPA2-AES, the uplink's band, visible.
        "security": "wpa2",
        "band": "auto",
        "hidden": False,
        "isolation": False,
        # Windows: Settings → Hotspot changes to push into Windows' own Mobile
        # hotspot. Set only when the user edits the page; cleared once applied,
        # so Windows' own settings stay the truth otherwise.
        "apply_on_windows": False,
    },
    "alerts": {
        "data_percent": 10,
        "data_gb": 1.0,
        "expiry_days": 3,
        "auto_refresh_hours": 6,
    },
    "speedtest": {
        "url": "https://www.google.com/generate_204",
        "timeout_s": 10,
        "batch_size": 50,
    },
    "geo": {
        # Matches the source scripts/fetch_deps.py bundles.
        "source": "Loyalsoldier",
        "auto_update_hours": 0,  # 0 = off
        "last_update": 0,  # epoch seconds; 0 = never
    },
    # Advanced Xray core options (Phase 5). All opt-in -- see core/coreopts.py.
    # With every value at its default, coreopts' apply_* functions are all
    # no-ops, so an untouched install renders exactly what it always has.
    "core": {
        "fragment": {
            "enabled": False, "packets": "tlshello",
            "length": "100-200", "interval": "10-20", "max_split": 0,
        },
        "mux": {
            "enabled": False, "concurrency": 8,
            "xudp_concurrency": 16, "xudp_proxy_udp443": "reject",
        },
        "sniffing": {"enabled": True, "route_only": False},
        "socks_port": 10808,
        "allow_lan": False,
        "lan_user": "",
        "lan_pass": "",
        "default_fp": "",
        # TCP socket options for the proxy connection. All off: an untouched
        # install renders exactly what it always has (see coreopts.apply_sockopt).
        "sockopt": {"tcp_fast_open": False, "tcp_mptcp": False, "tcp_congestion": ""},
        # Junk UDP packets before a Hysteria2 handshake. Off: see coreopts.apply_udp_noise.
        "udp_noise": {"enabled": False, "length": "10-20", "delay": "10-16"},
    },
    # Multi-exit SOCKS port (core/exits.py). Off: nothing is rendered for it.
    # items is a list of {"user", "profile_uid"}: a list, not a map, so _merge
    # keeps it whole (see dns.hosts).
    "exits": {"enabled": False, "port": 10809, "password": "", "items": []},
    # Port forwards (core/forwards.py): a list of {"port", "target": "host:port",
    # "via": "proxy"|"direct", "network"}. Empty: nothing is rendered for it.
    "forwards": [],
    "startup": {
        "start_on_login": False,
        "start_minimized": False,
        "auto_connect": False,
    },
    "updates": {
        "check": True,
        "last_check": 0,  # epoch seconds; 0 = never
        "notified_version": "",  # the last version a tray message was shown for
    },
}


def _stamp_v1(data: dict) -> dict:
    # No shape change yet: schema_version itself is the only thing being
    # introduced. Later migrations reshape a specific key the way this one
    # only stamps the version.
    data["schema_version"] = 1
    return data


# Ordered (target_version, migration) pairs, applied in sequence starting
# from the saved file's schema_version (0 for a file with no such key).
_MIGRATIONS: list[tuple[int, Callable[[dict], dict]]] = [
    (1, _stamp_v1),
]


def _migrate(data: dict) -> dict:
    version = data.get("schema_version", 0)
    for target, migrate in _MIGRATIONS:
        if version < target:
            data = migrate(data)
            version = target
    return data


def _merge(base: dict, over: dict) -> dict:
    """Overlay saved values on the defaults, dropping keys we no longer define."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k not in out:
            continue  # stale key from an older version
        if isinstance(v, dict) and isinstance(out[k], dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _path():
    return paths.base_dir() / "settings.json"


def load() -> dict:
    p = _path()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            raw = None
        # A settings.json that parses but isn't an object (corruption, or
        # something else wrote to the path) is as unusable as invalid JSON;
        # _migrate/_merge both assume a dict and would raise AttributeError
        # on anything else, which would stop the app from starting at all.
        if isinstance(raw, dict):
            merged = _merge(DEFAULTS, _migrate(raw))
            if merged.get("language") not in ("en", "fa"):
                merged["language"] = "en"
            return merged
    return copy.deepcopy(DEFAULTS)


def save(data: dict) -> None:
    _path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
