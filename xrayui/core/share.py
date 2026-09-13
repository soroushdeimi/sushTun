"""Turn a Profile back into a share link: the reverse of importer.py."""
from __future__ import annotations

import base64
import json
from urllib.parse import quote, urlencode

from .profiles import Profile


def _authority(address: str, port: int) -> str:
    if ":" in address and not address.startswith("["):
        return f"[{address}]:{port}"
    return f"{address}:{port}"


def _transport_query(p: Profile) -> dict[str, str]:
    """Transport/TLS query keys shared by vless, trojan and the std vmess://
    URI form -- the reverse of importer._std_query_fields."""
    q: dict[str, str] = {
        "type": p.network or "tcp",
        "security": p.security or "none",
    }
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
    if p.network == "tcp" and p.header_type:
        q["headerType"] = p.header_type
    if p.network == "xhttp":
        if p.xhttp_mode:
            q["mode"] = p.xhttp_mode
        if p.xhttp_extra:
            q["extra"] = p.xhttp_extra
    if p.allow_insecure:
        q["allowInsecure"] = "1"
    if p.ech:
        q["ech"] = p.ech
    if p.pcs:
        q["pcs"] = p.pcs
    if p.vcn:
        q["vcn"] = p.vcn
    return q


def _vless_query(p: Profile) -> dict[str, str]:
    q: dict[str, str] = {"encryption": p.encryption or "none"}
    q.update(_transport_query(p))
    if p.flow:
        q["flow"] = p.flow
    return q


def share_vless(p: Profile) -> str:
    query = urlencode(_vless_query(p), quote_via=quote)
    userinfo = quote(p.id, safe="")
    return f"vless://{userinfo}@{_authority(p.address, p.port)}?{query}#{quote(p.name)}"


def share_trojan(p: Profile) -> str:
    query = urlencode(_transport_query(p), quote_via=quote)
    userinfo = quote(p.id, safe="")
    return f"trojan://{userinfo}@{_authority(p.address, p.port)}?{query}#{quote(p.name)}"


def _vmess_dict(p: Profile) -> dict:
    """The legacy base64(JSON) vmess:// form -- v2rayN's VmessQRCode shape.
    grpc uses host as the service authority and path as the service name;
    xhttp's "type" doubles as the mode, tcp's as the raw header type. No
    "aid": Xray 26.3 is AEAD-only and has no alterId concept to write.
    """
    net = p.network or "tcp"
    host, path, service_name = p.host, p.path, p.service_name
    if net == "grpc":
        path, service_name = service_name, ""
    type_field = ""
    if net == "xhttp":
        type_field = p.xhttp_mode
    elif net == "tcp":
        type_field = p.header_type
    data: dict = {
        "v": "2", "ps": p.name, "add": p.address, "port": p.port, "id": p.id,
        "scy": p.vmess_security or "auto", "net": net, "type": type_field,
        "host": host, "path": path, "tls": p.security or "none",
        "sni": p.sni, "alpn": p.alpn, "fp": p.fp,
    }
    if p.allow_insecure:
        data["insecure"] = "1"
    if p.vcn:
        data["vcn"] = p.vcn
    if p.pcs:
        data["pcs"] = p.pcs
    return data


def share_vmess(p: Profile) -> str:
    encoded = base64.b64encode(
        json.dumps(_vmess_dict(p), ensure_ascii=False).encode()
    ).decode()
    return f"vmess://{encoded}"


def share_shadowsocks(p: Profile) -> str | None:
    """SIP002, base64url userinfo, plain tcp only. Anything SIP002 cannot
    express -- a transport, or an obfuscating header -- has no share link:
    a link that silently dropped the transport would point at a server
    that isn't actually listening the way the link implies.
    """
    if not p.ss_method or (p.network not in ("", "tcp")) or p.header_type:
        return None
    userinfo = base64.urlsafe_b64encode(f"{p.ss_method}:{p.id}".encode()).decode().rstrip("=")
    return f"ss://{userinfo}@{_authority(p.address, p.port)}#{quote(p.name)}"


def _hysteria2_query(p: Profile) -> dict[str, str]:
    q: dict[str, str] = {}
    if p.sni:
        q["sni"] = p.sni
    if p.alpn:
        q["alpn"] = p.alpn
    if p.allow_insecure:
        q["insecure"] = "1"
    if p.pcs:
        q["pinSHA256"] = p.pcs
    if p.vcn:
        q["vcn"] = p.vcn
    if p.ech:
        q["ech"] = p.ech
    if p.hy2_obfs_password:
        q["obfs"] = "salamander"
        q["obfs-password"] = p.hy2_obfs_password
    if p.hy2_ports:
        q["mport"] = p.hy2_ports
    return q


def share_hysteria2(p: Profile) -> str:
    query = urlencode(_hysteria2_query(p), quote_via=quote)
    userinfo = quote(p.id, safe="")
    return f"hysteria2://{userinfo}@{_authority(p.address, p.port)}?{query}#{quote(p.name)}"


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
    # safe="": a WireGuard private key is base64 and often contains "/",
    # which quote()'s default safe="/" would leave unescaped and end the
    # netloc (everything up to the next "/") before the "@" is even reached.
    userinfo = quote(p.id, safe="")
    return f"wireguard://{userinfo}@{_authority(p.address, p.port)}?{query}#{quote(p.name)}"


def share_link(p: Profile) -> str | None:
    protocol = (p.protocol or "").lower()
    if protocol == "wireguard":
        return share_wireguard(p)
    if protocol == "vmess":
        return share_vmess(p)
    if protocol == "trojan":
        return share_trojan(p)
    if protocol == "hysteria2":
        return share_hysteria2(p)
    if protocol == "shadowsocks":
        return share_shadowsocks(p)
    return share_vless(p)
