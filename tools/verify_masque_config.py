"""Opt-in native check: render real MASQUE profiles and validate them with
the bundled Xray binary via `xray run -test`.

This is a manual command, not part of the default unit suite, so the suite
stays portable and needs no Xray binary. It covers generic H2, generic H3
and a WARP identity built from a freshly generated dummy P-256 keypair.

Cases are produced by the real application path -- Profile + outbounds.build
-- so this verifies what the app actually renders, not a hand-built dict.
The only post-processing is dropping the interface placeholder from the
sockopt block, which the renderer normally fills with a live interface name
that a -test fixture does not have.

The dummy keypair comes from `xray tls cert -json` (a real P-256 key; the
PEM label it prints is misleading, the DER carries the id-ecPublicKey and
prime256v1 OIDs). The private key is used only in a throwaway config file
and is never printed. No enrollment, no live network.

Usage (from the repo root):
    python -m tools.verify_masque_config [path/to/xray]

The xray binary is taken from the argument if given, otherwise from the
project's paths.xray_exe().
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from xrayui import paths
from xrayui.core import outbounds
from xrayui.core.profiles import Profile

# OIDs: id-ecPublicKey (1.2.840.10045.2.1) and prime256v1 (1.2.840.10045.3.1.7).
_EC_ALGID = bytes.fromhex("301306072a8648ce3d020106082a8648ce3d030107")


def _generate_dummy_p256(xray: Path) -> tuple[str, str]:
    """Return (private_key_b64, public_key_b64) for a fresh dummy P-256 key.

    The private key is the PKCS8 DER body; the public key is the SPKI
    SEQUENCE taken from the self-signed certificate.
    """
    out = subprocess.run(
        [str(xray), "tls", "cert", "-json", "-domain=example.com"],
        capture_output=True, text=True, check=True, timeout=30,
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


def _strip_interface(outbound: dict) -> dict:
    """Drop the interface placeholder the renderer leaves for a live iface."""
    stream = outbound.get("streamSettings") or {}
    sockopt = stream.get("sockopt") or {}
    if "interface" in sockopt:
        del sockopt["interface"]
        if not sockopt:
            stream.pop("sockopt", None)
    return outbound


def _config(outbound: dict) -> str:
    return json.dumps({
        "log": {"loglevel": "warning"},
        "inbounds": [],
        "outbounds": [_strip_interface(outbound),
                      {"tag": "direct", "protocol": "freedom"}],
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


def _base_profile(**over) -> Profile:
    base = dict(name="verify", protocol="masque", address="162.159.198.2",
                port=443, network="masque", security="tls",
                sni="consumer-masque.cloudflareclient.com")
    base.update(over)
    return Profile(**base)


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        xray = Path(argv[1])
    else:
        xray = paths.xray_exe()
    if not xray.exists():
        print(f"FAIL: xray binary not found at {xray}")
        return 1

    cases: list[tuple[str, str]] = [
        ("generic h2", _config(outbounds.build(
            _base_profile(username="user", id="pass"), "proxy"))),
        ("generic h3", _config(outbounds.build(
            _base_profile(masque_http_version="h3",
                          masque_remote_dns="1.1.1.1, 2606:4700:4700::1111"),
            "proxy"))),
    ]
    try:
        priv, pub = _generate_dummy_p256(xray)
    except Exception as e:
        # A required case cannot be skipped: without a key the WARP case is
        # impossible, so the whole check fails rather than passing silently.
        print(f"FAIL: could not generate dummy P-256 key: {e}")
        return 1
    cases.append(("warp h2", _config(outbounds.build(
        _base_profile(masque_private_key=priv, masque_public_key=pub,
                      masque_addresses="172.16.0.2/32, 2606:4700:110:8a36::2/128"),
        "proxy"))))

    failures = 0
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
