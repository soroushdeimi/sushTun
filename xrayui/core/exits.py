"""Multi-exit port: one local SOCKS port, a different server per username.

Off by default. When on, a client picks its exit with the SOCKS username
(socks5://<user>:<password>@127.0.0.1:<port>). Xray copies that username into
the session's user email (proxy/socks/protocol.go, 26.3.27), so a routing rule
with "user" sends it to that exit's own outbound. SOCKS UDP never carries the
username, so UDP is refused on this port instead of leaking out of the main
server.

Nothing here may stop the main connection: a bad or busy setting drops the
whole feature and says why.
"""
from __future__ import annotations

import re
import socket
from dataclasses import dataclass

from . import coreopts, outbounds
from .metrics import STATS_API_PORT
from .profiles import Profile

INBOUND_TAG = "exits-in"
USER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


@dataclass
class Exit:
    user: str
    profile: Profile


def outbound_tag(profile: Profile) -> str:
    return f"exit-{profile.uid}"


def reserved_ports(core_cfg: dict) -> set[int]:
    return {53, STATS_API_PORT, coreopts.valid_socks_port((core_cfg or {}).get("socks_port"))}


def port_problem(port, core_cfg: dict) -> str | None:
    """Why `port` can't be used (static check), or None."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        return "the port must be between 1024 and 65535"
    if port in reserved_ports(core_cfg):
        return f"port {port} is already used by sushTun"
    return None


def items_problem(items, known_uids: set[str]) -> str | None:
    """Why the exit list can't be saved, or None."""
    if not isinstance(items, list) or not items:
        return "add at least one exit"
    seen: set[str] = set()
    for item in items:
        user = str((item or {}).get("user") or "") if isinstance(item, dict) else ""
        if not USER_RE.match(user):
            return f"'{user}' is not a valid username (a-z, 0-9 and -, up to 32)"
        if user in seen:
            return f"the username '{user}' is used twice"
        seen.add(user)
        if item.get("profile_uid") not in known_uids:
            return f"the server for '{user}' no longer exists"
    return None


def port_is_free(port: int) -> bool:
    """A bind test on the address Xray will listen on. Xray exits when its
    port is taken, which would take the main connection down with it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def prepare(exits_cfg: dict | None, core_cfg: dict | None,
            get_profile) -> tuple[list[Exit], str | None]:
    """The exits to render, and a warning when the feature had to be dropped.

    Returns ([], None) when the feature is off. Any problem drops the whole
    feature (never a partial set), so a username can't silently land on the
    wrong server.
    """
    cfg = exits_cfg or {}
    if cfg.get("enabled") is not True:
        return [], None
    port = cfg.get("port")
    why = port_problem(port, core_cfg or {})
    if why is None and not str(cfg.get("password") or ""):
        why = "a password is required"
    items = cfg.get("items")
    profiles: dict[str, Profile] = {}
    if why is None and isinstance(items, list):
        for item in items:
            uid = item.get("profile_uid") if isinstance(item, dict) else None
            profile = get_profile(uid) if uid else None
            if profile is not None:
                profiles[uid] = profile
    if why is None:
        why = items_problem(items, set(profiles))
    if why is None and not port_is_free(port):
        why = f"port {port} is in use by another program"
    if why is not None:
        return [], f"Multi-exit port is off for this connection: {why}."
    return [Exit(item["user"], profiles[item["profile_uid"]]) for item in items], None


def apply(cfg: dict, exits: list[Exit], exits_cfg: dict, core_cfg: dict | None,
          active: Profile) -> list[dict]:
    """Add the inbound and one outbound per exit; return the routing rules.

    The rules must go before every user rule (render inserts them right
    after the DNS rules), so an exit always wins over Iran-direct and the
    other simple switches.
    """
    if not exits:
        return []
    cfg.setdefault("inbounds", []).append({
        "tag": INBOUND_TAG, "listen": "127.0.0.1", "port": exits_cfg["port"],
        "protocol": "socks",
        "settings": {"auth": "password", "udp": False,
                     "accounts": [{"user": e.user, "pass": str(exits_cfg["password"])}
                                  for e in exits]},
    })
    rules: list[dict] = []
    built: set[str] = set()
    for e in exits:
        if e.profile.uid == active.uid:
            tag = "proxy"  # the live server already has its outbound
        else:
            tag = outbound_tag(e.profile)
            if tag not in built:
                cfg["outbounds"].append(_exit_outbound(e.profile, tag, core_cfg))
                built.add(tag)
        rules.append({"type": "field", "inboundTag": [INBOUND_TAG], "user": [e.user],
                      "outboundTag": tag})
    # Anything else on this port (it can't be a known user) goes nowhere.
    rules.append({"type": "field", "inboundTag": [INBOUND_TAG], "outboundTag": "block"})
    return rules


def _exit_outbound(profile: Profile, tag: str, core_cfg: dict | None) -> dict:
    # Built under the "proxy" tag first, in a config of its own, so every
    # core option (fingerprint, fragment, mux, TCP tuning, UDP noise) applies
    # exactly as it does to the main server, with no change to coreopts.
    outbound = outbounds.build(profile, "proxy")
    if core_cfg:
        coreopts.apply_all({"outbounds": [outbound]}, core_cfg, profile)
    outbound["tag"] = tag
    return outbound
