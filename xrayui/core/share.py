"""Turn a Profile back into a share link: the reverse of importer.py."""
from __future__ import annotations

from urllib.parse import quote, urlencode

from .profiles import Profile


def _authority(address: str, port: int) -> str:
    if ":" in address and not address.startswith("["):
        return f"[{address}]:{port}"
    return f"{address}:{port}"


def _vless_query(p: Profile) -> dict[str, str]:
    q: dict[str, str] = {
        "encryption": p.encryption or "none",
        "type": p.network or "tcp",
        "security": p.security or "none",
    }
    if p.flow:
        q["flow"] = p.flow
    if p.sni:
        q["sni"] = p.sni
    if p.fp:
        q["fp"] = p.fp
    if p.alpn:
        q["alpn"] = p.alpn
    if p.pbk:
        q["pbk"] = p.pbk
    if p.sid:
        q["sid"] = p.sid
    if p.spx:
        q["spx"] = p.spx
    if p.path:
        q["path"] = p.path
    if p.host:
        q["host"] = p.host
    if p.network == "grpc" and p.service_name:
        q["serviceName"] = p.service_name
    return q


def share_vless(p: Profile) -> str:
    query = urlencode(_vless_query(p), quote_via=quote)
    return f"vless://{quote(p.id)}@{_authority(p.address, p.port)}?{query}#{quote(p.name)}"


def _wireguard_query(p: Profile) -> dict[str, str]:
    q: dict[str, str] = {"publickey": p.pbk}
    if p.wg_local_address:
        q["address"] = p.wg_local_address
    if p.wg_preshared:
        q["presharedkey"] = p.wg_preshared
    if p.wg_reserved:
        q["reserved"] = p.wg_reserved
    if p.wg_mtu and p.wg_mtu != 1420:
        q["mtu"] = str(p.wg_mtu)
    if p.wg_keepalive:
        q["keepalive"] = str(p.wg_keepalive)
    return q


def share_wireguard(p: Profile) -> str:
    query = urlencode(_wireguard_query(p), quote_via=quote)
    return f"wireguard://{quote(p.id)}@{_authority(p.address, p.port)}?{query}#{quote(p.name)}"


def share_link(p: Profile) -> str:
    if (p.protocol or "").lower() == "wireguard":
        return share_wireguard(p)
    return share_vless(p)
