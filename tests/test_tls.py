"""Outbound HTTPS must find a CA bundle on distros the build machine doesn't match.

A frozen Python's OpenSSL defaults point at the build machine's layout
(Ubuntu), so on Fedora every HTTPS fetch died with "unable to get local
issuer certificate". core/tls.py falls back to the usual bundle locations,
and never turns verification off.
"""
from __future__ import annotations

import socket
import ssl
import subprocess
import threading
import urllib.request
from types import SimpleNamespace

import pytest

from xrayui.core import subscription, tls

OPENSSL = subprocess.run(["which", "openssl"], capture_output=True, text=True).stdout.strip()
needs_openssl = pytest.mark.skipif(not OPENSSL, reason="the openssl CLI is not installed")


def _openssl(*args, cwd):
    subprocess.run([OPENSSL, *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    """A throwaway CA plus a localhost server certificate signed by it."""
    if not OPENSSL:
        pytest.skip("the openssl CLI is not installed")
    d = tmp_path_factory.mktemp("pki")
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem",
             "-days", "2", "-subj", "/CN=sushtun-test-ca",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=d)
    _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "srv.key", "-out", "srv.csr",
             "-subj", "/CN=localhost", cwd=d)
    (d / "ext.cnf").write_text("subjectAltName=DNS:localhost,IP:127.0.0.1\n"
                               "basicConstraints=CA:FALSE\n"
                               "authorityKeyIdentifier=keyid\n")
    _openssl("x509", "-req", "-in", "srv.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
             "-CAcreateserial", "-out", "srv.pem", "-days", "2", "-extfile", "ext.cnf", cwd=d)
    return SimpleNamespace(dir=d, ca=d / "ca.pem", cert=d / "srv.pem", key=d / "srv.key")


def _no_default_cafile():
    return SimpleNamespace(cafile=None, capath=None)


def _has_test_ca(ctx):
    return any(("commonName", "sushtun-test-ca") in rdn
               for cert in ctx.get_ca_certs() for rdn in cert["subject"])


@pytest.fixture(autouse=True)
def _fresh_cache():
    tls.https_context.cache_clear()
    yield
    tls.https_context.cache_clear()


@needs_openssl
def test_first_existing_bundle_is_loaded_when_the_default_is_missing(pki, tmp_path):
    ctx, found = tls.load_context([tmp_path / "missing.crt", pki.ca],
                                  verify_paths=_no_default_cafile())
    assert found and _has_test_ca(ctx)


@needs_openssl
def test_the_default_bundle_is_left_alone_when_it_exists(pki):
    ctx, found = tls.load_context([pki.ca], verify_paths=SimpleNamespace(cafile="/x", capath=None))
    assert found and not _has_test_ca(ctx)


@needs_openssl
def test_unreadable_candidates_are_skipped(pki, tmp_path):
    junk = tmp_path / "junk.crt"
    junk.write_text("not a certificate")
    ctx, found = tls.load_context([tmp_path, junk, pki.ca], verify_paths=_no_default_cafile())
    assert found and _has_test_ca(ctx)


def test_nothing_found_keeps_the_honest_default_without_raising(tmp_path):
    ctx, found = tls.load_context([tmp_path / "a", tmp_path / "b"], verify_paths=_no_default_cafile())
    assert not found
    assert isinstance(ctx, ssl.SSLContext)


@needs_openssl
@pytest.mark.parametrize("candidates", [[], ["missing"], ["pki"]])
def test_verification_is_never_relaxed(pki, tmp_path, candidates):
    paths = [pki.ca if c == "pki" else tmp_path / c for c in candidates]
    ctx, _found = tls.load_context(paths, verify_paths=_no_default_cafile())
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_a_directory_default_counts_as_found(tmp_path):
    ctx, found = tls.load_context([], verify_paths=SimpleNamespace(cafile=None, capath=str(tmp_path)))
    assert found


@pytest.fixture
def tls_server(pki):
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(pki.cert, pki.key)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    stop = threading.Event()

    def serve():
        sock.settimeout(0.2)
        while not stop.is_set():
            try:
                raw, _ = sock.accept()
            except (TimeoutError, OSError):
                continue
            try:
                with server_ctx.wrap_socket(raw, server_side=True) as conn:
                    conn.recv(4096)
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            except (ssl.SSLError, OSError):
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield sock.getsockname()[1]
    stop.set()
    thread.join(2)
    sock.close()


@needs_openssl
def test_a_real_handshake_needs_the_ca_we_loaded(pki, tls_server):
    url = f"https://localhost:{tls_server}/"
    trusted, _ = tls.load_context([pki.ca], verify_paths=_no_default_cafile())
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=trusted))
    with opener.open(url, timeout=5) as resp:
        assert resp.read() == b"ok"
    untrusted, _ = tls.load_context([], verify_paths=_no_default_cafile())
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=untrusted))
    with pytest.raises(urllib.error.URLError) as err:
        opener.open(url, timeout=5)
    assert isinstance(err.value.reason, ssl.SSLCertVerificationError)


def test_the_subscription_opener_uses_the_shared_context():
    subscription._opener.cache_clear()
    opener = subscription._opener()
    https = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPSHandler)]
    assert len(https) == 1 and https[0]._context is tls.https_context()


def test_hint_only_for_a_verify_failure_when_no_bundle_was_found(monkeypatch):
    err = "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate>"
    monkeypatch.setattr(tls, "ca_found", lambda: False)
    assert tls.needs_ca_hint(err)
    assert not tls.needs_ca_hint("<urlopen error timed out>")
    monkeypatch.setattr(tls, "ca_found", lambda: True)
    assert not tls.needs_ca_hint(err)
