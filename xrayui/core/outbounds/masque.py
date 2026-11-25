"""MASQUE outbound builder (CONNECT-IP over HTTP/2 or HTTP/3).

Wire shape verified against the bundled Xray 26.10.31 binary: protocol
"masque", settings {address, port, remoteDNS}, streamSettings.network
"masque", security "tls", masqueSettings {host, path, user, pass, warp},
and tlsSettings.alpn carrying the single h2/h3 carrier.
"""
from __future__ import annotations

from ..profiles import Profile, normalize_pcs, valid_pcs
from ._common import _PLACEHOLDER


def _split_csv(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").replace("\n", ",").split(",") if x.strip()]


def apply(proxy: dict, p: Profile) -> None:
    proxy["protocol"] = "masque"
    settings: dict = {"address": p.address, "port": p.port}
    dns = _split_csv(p.masque_remote_dns)
    if dns:
        settings["remoteDNS"] = dns
    proxy["settings"] = settings

    masque: dict = {}
    if p.host:
        masque["host"] = p.host
    if p.path:
        masque["path"] = p.path
    warp = (p.masque_private_key, p.masque_public_key, p.masque_addresses)
    if any(warp) and not all(warp):
        # A partial WARP identity must not silently become anonymous generic.
        raise ValueError("partial WARP identity: set all of private/public/addresses")
    if all(warp):
        masque["warp"] = {
            "privateKey": p.masque_private_key,
            "publicKey": p.masque_public_key,
            "address": _split_csv(p.masque_addresses),
        }
    elif p.username and p.id:
        masque["user"] = p.username
        masque["pass"] = p.id
    proxy["streamSettings"] = {
        "network": "masque",
        "security": "tls",
        "sockopt": {"interface": _PLACEHOLDER},
        "masqueSettings": masque,
        "tlsSettings": _tls(p),
    }


def _tls(p: Profile) -> dict:
    tls: dict = {}
    if p.sni:
        tls["serverName"] = p.sni
    if p.fp:
        tls["fingerprint"] = p.fp
    # Single carrier: the http version is the only ALPN advertised.
    tls["alpn"] = [p.masque_http_version]
    if p.pcs:
        pcs = normalize_pcs(p.pcs)
        if valid_pcs(pcs):
            tls["pinnedPeerCertSha256"] = pcs
    if p.vcn:
        tls["verifyPeerCertByName"] = p.vcn
    # allow_insecure is never rendered: the bundled Xray hard-refuses it.
    return tls
