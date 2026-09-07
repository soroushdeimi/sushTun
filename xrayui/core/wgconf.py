"""Pure WireGuard config helpers: UAPI payloads and .conf rendering.

No I/O here — callers resolve hostnames and talk to sockets/pipes themselves
(see wireguard.py). Keeping this module pure makes it trivially unit-testable.
"""
from __future__ import annotations

import base64

from .profiles import Profile

_FULL_TUNNEL = {"0.0.0.0/0", "::/0"}


def b64_to_hex(key: str) -> str:
    """WireGuard keys are stored base64; the UAPI wants hex."""
    return base64.b64decode(key.strip()).hex()


def allowed_ips(profile: Profile) -> list[str]:
    ips = [a.strip() for a in (profile.wg_allowed_ips or "").split(",") if a.strip()]
    return ips or ["0.0.0.0/0", "::/0"]


def local_addresses(profile: Profile) -> list[str]:
    return [a.strip() for a in (profile.wg_local_address or "").split(",") if a.strip()]


def is_full_tunnel(profile: Profile) -> bool:
    return any(ip in _FULL_TUNNEL for ip in allowed_ips(profile))


def has_reserved(profile: Profile) -> bool:
    """wireguard-go has no Reserved field — that's an Xray/WARP extension."""
    return bool((profile.wg_reserved or "").strip())


def endpoint_string(profile: Profile, host_override: str | None = None) -> str:
    host = host_override if host_override is not None else profile.address
    if ":" in host and not host.startswith("["):
        return f"[{host}]:{profile.port}"
    return f"{host}:{profile.port}"


def uapi_payload(profile: Profile, endpoint_ip: str | None = None) -> str:
    """Build the `set=1` UAPI block. Endpoint must be a literal IP:port —
    pass endpoint_ip (already resolved by the caller) when profile.address
    is a hostname; wireguard-go's UAPI does not resolve hostnames itself.
    """
    lines = [
        "set=1",
        f"private_key={b64_to_hex(profile.id)}",
        "listen_port=0",
        "replace_peers=true",
        f"public_key={b64_to_hex(profile.pbk)}",
    ]
    if profile.wg_preshared:
        lines.append(f"preshared_key={b64_to_hex(profile.wg_preshared)}")
    lines.append(f"endpoint={endpoint_string(profile, endpoint_ip)}")
    if profile.wg_keepalive:
        lines.append(f"persistent_keepalive_interval={int(profile.wg_keepalive)}")
    lines.append("replace_allowed_ips=true")
    for ip in allowed_ips(profile):
        lines.append(f"allowed_ip={ip}")
    return "\n".join(lines) + "\n\n"


def render_conf(profile: Profile) -> str:
    """A standard .conf, for export/debug — not used to drive wireguard-go."""
    lines = ["[Interface]", f"PrivateKey = {profile.id}"]
    addrs = local_addresses(profile)
    if addrs:
        lines.append(f"Address = {', '.join(addrs)}")
    if profile.wg_mtu:
        lines.append(f"MTU = {int(profile.wg_mtu)}")
    lines.append("")
    lines.append("[Peer]")
    lines.append(f"PublicKey = {profile.pbk}")
    if profile.wg_preshared:
        lines.append(f"PresharedKey = {profile.wg_preshared}")
    lines.append(f"Endpoint = {endpoint_string(profile)}")
    lines.append(f"AllowedIPs = {', '.join(allowed_ips(profile))}")
    if profile.wg_keepalive:
        lines.append(f"PersistentKeepalive = {int(profile.wg_keepalive)}")
    return "\n".join(lines) + "\n"
