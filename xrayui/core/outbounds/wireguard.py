"""WireGuard outbound builder."""
from __future__ import annotations

from ..profiles import Profile


def _wg_endpoint(p: Profile) -> str:
    addr = p.address
    if ":" in addr and not addr.startswith("["):
        return f"[{addr}]:{p.port}"
    return f"{addr}:{p.port}"


def _wg_reserved(raw: str) -> list[int]:
    s = (raw or "").strip().strip("[]")
    if not s:
        return []
    s = s.replace("-", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) == 3 and all(p.lstrip("+-").isdigit() for p in parts):
        return [int(p) & 0xFF for p in parts]
    return []


def apply(proxy: dict, p: Profile) -> None:
    # Xray WireGuard outbounds do not accept streamSettings.
    proxy.pop("streamSettings", None)
    addrs = [a.strip() for a in (p.wg_local_address or "").split(",") if a.strip()]
    allowed = [a.strip() for a in (p.wg_allowed_ips or "").split(",") if a.strip()]
    peer: dict = {
        "endpoint": _wg_endpoint(p),
        "publicKey": p.pbk,
        "allowedIPs": allowed or ["0.0.0.0/0", "::/0"],
    }
    if p.wg_preshared:
        peer["preSharedKey"] = p.wg_preshared
    if p.wg_keepalive:
        peer["keepAlive"] = int(p.wg_keepalive)
    settings: dict = {
        "secretKey": p.id,
        "peers": [peer],
        "mtu": int(p.wg_mtu) if p.wg_mtu else 1420,
        "noKernelTun": True,
        "domainStrategy": "ForceIP",
    }
    if addrs:
        settings["address"] = addrs
    reserved = _wg_reserved(p.wg_reserved)
    if reserved:
        settings["reserved"] = reserved
    proxy["protocol"] = "wireguard"
    proxy["settings"] = settings
