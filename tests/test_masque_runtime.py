"""MASQUE runtime data-plane probe: real local H2/H3 + chain, no TUN/routes/DNS.

The probe (tools/masque_runtime_probe.py) stands up an isolated local MASQUE
TLS server, a VLESS/TCP exit and an HTTP target in a temp dir, and drives real
Xray processes. It must not touch OS routes, DNS or TUN. The integration test
runs the whole probe and asserts the H2 standalone data plane actually returns
application bytes (not just a TLS handshake).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools import masque_runtime_probe as probe

PROBE = Path(__file__).resolve().parent.parent / "tools" / "masque_runtime_probe.py"


def _xray() -> Path:
    # The contract pins the baseline Xray at the sushTun checkout; the probe's
    # default points there. Fall back to the bundled binary if present.
    if probe.DEFAULT_XRAY.exists():
        return probe.DEFAULT_XRAY
    from xrayui import paths
    return paths.xray_exe()


# -- pure helpers (no xray, no network) --------------------------------------
def test_cert_sha256_is_64_hex(tmp_path):
    import subprocess as sp

    from tools import masque_runtime_probe as probe

    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    sp.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert), "-days", "1",
            "-subj", "/CN=t"], check=True, capture_output=True)
    pin = probe._cert_sha256(cert)
    assert re.fullmatch(r"[0-9a-f]{64}", pin)


def test_local_ip_is_not_loopback_or_linklocal():
    from tools import masque_runtime_probe as probe

    ip = probe._local_ip()
    assert not ip.startswith("127.")
    assert not ip.startswith("169.254.")


def test_free_port_is_in_range():
    from tools import masque_runtime_probe as probe

    assert 1 <= probe._free_port() <= 65535


# -- real data plane ----------------------------------------------------------
def test_h2_standalone_data_plane(tmp_path):
    exe = _xray()
    if not exe.exists():
        pytest.fail("bundled xray binary not present")
    out = subprocess.run(
        [sys.executable, str(PROBE), "--xray", str(exe)],
        capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "PASS  H2 standalone data plane: HTTP 200" in out.stdout
    # TLS-only is not data-plane success: the body must be non-empty.
    m = re.search(r"H2 standalone data plane: HTTP 200 size=(\d+)B", out.stdout)
    assert m and int(m.group(1)) > 0
    # Wrong credentials must be rejected, not silently accepted.
    assert "PASS  H2 wrong credentials rejected" in out.stdout


def test_chain_masque_to_vless_data_plane(tmp_path):
    exe = _xray()
    if not exe.exists():
        pytest.fail("bundled xray binary not present")
    out = subprocess.run(
        [sys.executable, str(PROBE), "--xray", str(exe)],
        capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "PASS  chain MASQUE->VLESS data plane: HTTP 200" in out.stdout
