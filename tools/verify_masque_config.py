"""Opt-in native check: render MASQUE configs and validate them with the
bundled Xray binary via `xray run -test`.

This is a manual command, not part of the default unit suite, so the suite
stays portable and needs no Xray binary. It covers generic H2, generic H3
and a WARP identity built from a freshly generated dummy P-256 keypair.

The dummy keypair comes from `xray tls cert -json` (a real P-256 key; the
PEM label it prints is misleading, the DER carries the id-ecPublicKey and
prime256v1 OIDs). The private key is used only in a throwaway config file
and is never printed. No enrollment, no live network.

Usage:
    python tools/verify_masque_config.py [path/to/xray]
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_XRAY = Path(
    "/Users/soroushdeimi/Desktop/myprojects/SUSHTUN/sushTun/xray"
)

# OIDs: id-ecPublicKey (1.2.840.10045.2.1) and prime256v1 (1.2.840.10045.3.1.7).
_EC_ALGID = bytes.fromhex("301306072a8648ce3d020106082a8648ce3d030107")


def _generate_dummy_p256(xray: Path) -> tuple[str, str]:
    """Return (private_key_b64, public_key_b64) for a fresh dummy P-256 key.

    The private key is the PKCS8 DER body; the public key is the SPKI
    SEQUENCE taken from the self-signed certificate.
    """
    out = subprocess.run(
        [str(xray), "tls", "cert", "-json", "-domain=example.com"],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    key = "\n".join(data["key"])
    cert = "\n".join(data["certificate"])
    pkcs8 = base64.b64decode("".join(line for line in key.splitlines()[1:-1]))
    certder = base64.b64decode("".join(line for line in cert.splitlines()[1:-1]))
    idx = certder.find(_EC_ALGID)
    if idx < 0 or certder[idx - 2] != 0x30:
        raise RuntimeError("could not locate the P-256 SPKI in the certificate")
    spki_len = certder[idx - 1]
    spki = certder[idx - 2:idx - 2 + 2 + spki_len]
    return base64.b64encode(pkcs8).decode(), base64.b64encode(spki).decode()


def _masque_outbound(hv: str, *, warp: dict | None = None,
                     user: str = "", pas: str = "",
                     dns: list[str] | None = None) -> dict:
    settings: dict = {"address": "162.159.198.2", "port": 443}
    if dns:
        settings["remoteDNS"] = dns
    masque: dict = {}
    if warp:
        masque["warp"] = warp
    if user:
        masque["user"] = user
        masque["pass"] = pas
    return {
        "tag": "proxy", "protocol": "masque", "settings": settings,
        "streamSettings": {
            "network": "masque", "security": "tls",
            "masqueSettings": masque,
            "tlsSettings": {"alpn": [hv],
                            "serverName": "consumer-masque.cloudflareclient.com"},
        },
    }


def _config(outbound: dict) -> str:
    return json.dumps({
        "log": {"loglevel": "warning"},
        "inbounds": [],
        "outbounds": [outbound, {"tag": "direct", "protocol": "freedom"}],
    })


def _run_test(xray: Path, config_text: str) -> str | None:
    fd, tmp = tempfile.mkstemp(prefix="verify-masque-", suffix=".json")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(config_text)
        r = subprocess.run(
            [str(xray), "run", "-test", "-c", tmp],
            capture_output=True, text=True, timeout=20,
        )
    finally:
        Path(tmp).unlink(missing_ok=True)
    if r.returncode == 0:
        return None
    lines = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()]
    return lines[-1].rsplit(" > ", 1)[-1].strip() if lines else "xray -test failed"


def main(argv: list[str]) -> int:
    xray = Path(argv[1]) if len(argv) > 1 else DEFAULT_XRAY
    if not xray.exists():
        print(f"FAIL: xray binary not found at {xray}")
        return 1

    failures = 0
    cases: list[tuple[str, str]] = [
        ("generic h2", _config(_masque_outbound("h2", user="user", pas="pass"))),
        ("generic h3", _config(_masque_outbound(
            "h3", dns=["1.1.1.1", "2606:4700:4700::1111"]))),
    ]
    try:
        priv, pub = _generate_dummy_p256(xray)
    except Exception as e:
        print(f"SKIP: could not generate dummy P-256 key: {e}")
        priv = pub = None
    if priv:
        cases.append(("warp h2", _config(_masque_outbound("h2", warp={
            "privateKey": priv, "publicKey": pub,
            "address": ["172.16.0.2/32", "2606:4700:110:8a36::2/128"],
        }))))

    for name, cfg in cases:
        err = _run_test(xray, cfg)
        if err:
            failures += 1
            print(f"FAIL: {name}: {err}")
        else:
            print(f"OK:   {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
