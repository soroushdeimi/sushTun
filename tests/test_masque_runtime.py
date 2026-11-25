"""MASQUE runtime probe: portable unit tests only.

The native data-plane probe (tools/masque_runtime_probe.py) is an opt-in
manual diagnostic that drives real Xray processes; it is NOT part of the
default suite. These tests exercise the probe's pure helpers and the REAL
app builders (outbounds.build / chains.resolve+apply) that the probe feeds
to Xray, so the app's own builder/chain path is proven without a binary,
openssl or any non-loopback address.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request

import pytest

from tools import masque_runtime_probe as probe


# -- pure helpers -------------------------------------------------------------
def test_free_port_is_in_range():
    assert 1 <= probe._free_port() <= 65535


def test_strip_entry_interface_removes_placeholder_only():
    outbound = {"tag": "proxy", "streamSettings": {"sockopt": {"interface": "__IFACE__"}}}
    probe._strip_entry_interface(outbound)
    assert outbound["streamSettings"]["sockopt"] == {}
    # A non-placeholder interface is left untouched.
    other = {"streamSettings": {"sockopt": {"interface": "en0"}}}
    probe._strip_entry_interface(other)
    assert other["streamSettings"]["sockopt"] == {"interface": "en0"}


def test_cert_sha256_hex_encodes_der(monkeypatch):
    import hashlib

    der = b"\x30\x82fake-der-bytes"
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        class R:
            stdout = der if "x509" in cmd else hashlib.sha256(der).digest()
        return R()

    monkeypatch.setattr(probe.subprocess, "run", fake_run)
    pin = probe._cert_sha256(probe.Path("/nonexistent/cert.pem"))
    assert pin == hashlib.sha256(der).hexdigest()
    # Two steps: DER extraction, then SHA-256 of that DER.
    assert any("x509" in c for c in calls)
    assert any("dgst" in c and "-sha256" in c for c in calls)


# -- real app builders (no xray) ---------------------------------------------
def test_standalone_client_uses_real_masque_builder(tmp_path):
    cfg_path, _ = probe._client_cfg_standalone(tmp_path, 10800, 4433, "ab" * 32)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    out = next(o for o in cfg["outbounds"] if o["tag"] == "proxy")
    assert out["protocol"] == "masque"
    assert out["settings"]["address"] == "127.0.0.1"
    assert out["settings"]["port"] == 4433
    stream = out["streamSettings"]
    assert stream["network"] == "masque"
    assert stream["security"] == "tls"
    assert stream["tlsSettings"]["alpn"] == ["h2"]
    assert stream["tlsSettings"]["pinnedPeerCertSha256"] == "ab" * 32
    assert stream["masqueSettings"] == {"user": "u1", "pass": "p1"}
    # The loopback fixture strips only the interface placeholder.
    assert stream["sockopt"] == {}
    # socks-in inbound + routing to the proxy.
    assert any(i["tag"] == "socks-in" and i["listen"] == "127.0.0.1"
               for i in cfg["inbounds"])
    assert {"type": "field", "inboundTag": ["socks-in"], "outboundTag": "proxy"} \
        in cfg["routing"]["rules"]


def test_standalone_client_h3_carrier(tmp_path):
    cfg_path, _ = probe._client_cfg_standalone(tmp_path, 10801, 4433, "ab" * 32,
                                               http_version="h3")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    out = next(o for o in cfg["outbounds"] if o["tag"] == "proxy")
    assert out["streamSettings"]["tlsSettings"]["alpn"] == ["h3"]


def test_chain_client_uses_real_chains_apply(tmp_path):
    cfg_path, _ = probe._client_cfg_chain(tmp_path, 10802, 4433, 4434, "ab" * 32)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    tags = {o["tag"] for o in cfg["outbounds"]}
    assert "chain-1" in tags and "proxy" in tags
    entry = next(o for o in cfg["outbounds"] if o["tag"] == "chain-1")
    exit_ = next(o for o in cfg["outbounds"] if o["tag"] == "proxy")
    # Entry is the MASQUE hop; the exit dials through it.
    assert entry["protocol"] == "masque"
    assert entry["streamSettings"]["sockopt"] == {}  # interface stripped
    assert exit_["protocol"] == "vless"
    assert exit_["streamSettings"]["sockopt"] == {"dialerProxy": "chain-1"}
    assert exit_["settings"]["vnext"][0]["address"] == probe.DOC_VLESS_IP
    assert {"type": "field", "inboundTag": ["socks-in"], "outboundTag": "proxy"} \
        in cfg["routing"]["rules"]


# -- loopback-only fixtures (no external tools) ------------------------------
def test_socks_allowlist_forwards_only_mapped_destinations():
    port = probe._free_port()
    target_port = probe._free_port()
    # A tiny loopback echo server standing in for the mapped destination.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", target_port))
    srv.listen(4)

    def serve():
        conn, _ = srv.accept()
        conn.sendall(b"OK")
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    proxy = probe._socks5_allowlist(port, {("203.0.113.10", target_port):
                                           ("127.0.0.1", target_port)})
    try:
        time.sleep(0.3)
        # Mapped destination is forwarded to loopback.
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(b"\x05\x01\x00")
        assert s.recv(2) == b"\x05\x00"
        s.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("203.0.113.10")
                  + target_port.to_bytes(2, "big"))
        reply = s.recv(10)  # VER REP RSV ATYP BND.ADDR(4) BND.PORT(2)
        assert reply[1] == 0  # success
        assert s.recv(2) == b"OK"
        s.close()
        # Unknown destination is rejected (reply code 4).
        assert probe._socks_unknown_target(port) is True
    finally:
        proxy.terminate()
        proxy.wait(timeout=5)
        srv.close()


def test_http_target_serves_exact_body_on_loopback():
    port = probe._free_port()
    body = "EXACT-BODY-123"
    proc = probe._http_target(port, body.encode("ascii"))
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/",
                                            timeout=2) as r:
                    assert r.read().decode("ascii") == body
                return
            except OSError:
                time.sleep(0.1)
        pytest.fail("loopback HTTP target did not come up")
    finally:
        proc.terminate()
        proc.wait(timeout=5)
