"""Tests for the MASQUE probe helper. No real networking, no real Xray."""
import json
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from xrayui.core import masque_probe as mp
from xrayui.core.profiles import Profile


def _profile(**over):
    base = dict(
        name="m", protocol="masque", address="1.2.3.4", port=443,
        id="", username="", network="masque", security="tls",
        sni="example.com",
        masque_http_version="h2",
    )
    base.update(over)
    return Profile(**base)


# -- parse_endpoint ----------------------------------------------------------
def test_parse_endpoint_v4():
    assert mp.parse_endpoint("1.2.3.4:443") == ("1.2.3.4", 443)


def test_parse_endpoint_v6():
    assert mp.parse_endpoint("[2001:db8::1]:8443") == ("2001:db8::1", 8443)


@pytest.mark.parametrize("bad", ["", "1.2.3.4", "1.2.3.4:0", "1.2.3.4:70000",
                                 "1.2.3.4:abc", "[2001:db8::1", "[2001:db8::1]8443"])
def test_parse_endpoint_rejects(bad):
    with pytest.raises(ValueError):
        mp.parse_endpoint(bad)


# -- _build_config shape -----------------------------------------------------
def test_build_config_is_masque_single_carrier():
    p = _profile()
    cfg = mp._build_config(p, "1.2.3.4:443", 12345, "h2", "en0")
    ob = cfg["outbounds"][0]
    assert ob["protocol"] == "masque"
    assert ob["settings"] == {"address": "1.2.3.4", "port": 443}
    ss = ob["streamSettings"]
    assert ss["network"] == "masque"
    assert ss["security"] == "tls"
    # single carrier: alpn is exactly the one negotiated version
    assert ss["tlsSettings"]["alpn"] == ["h2"]
    assert "allowInsecure" not in ss and "realitySettings" not in ss
    # physical interface binding, speedtest convention
    assert ss["sockopt"]["interface"] == "en0"
    # isolated local HTTP inbound, no tun/dns/api
    ib = cfg["inbounds"][0]
    assert ib["protocol"] == "http" and ib["listen"] == "127.0.0.1"
    assert not any(i.get("tag") in ("tun-in", "api") for i in cfg["inbounds"])
    assert "stats" not in cfg and "api" not in cfg


def test_build_config_h3_alpn():
    p = _profile(masque_http_version="h3")
    cfg = mp._build_config(p, "1.2.3.4:443", 1, "h3", "en0")
    assert cfg["outbounds"][0]["streamSettings"]["tlsSettings"]["alpn"] == ["h3"]


def test_build_config_iface_round_trips():
    # A quoted/backslashed alias must land verbatim in the JSON, not be
    # string-replaced into the serialized text.
    alias = 'we"ird\\iface'
    cfg = mp._build_config(_profile(), "1.2.3.4:443", 1, "h2", alias)
    assert cfg["outbounds"][0]["streamSettings"]["sockopt"]["interface"] == alias


def test_build_config_no_iface_drops_placeholder():
    cfg = mp._build_config(_profile(), "1.2.3.4:443", 1, "h2", None)
    assert "interface" not in cfg["outbounds"][0]["streamSettings"]["sockopt"]


def test_build_config_remote_dns_must_be_ip():
    p = _profile(masque_remote_dns="1.1.1.1, 2606:4700:4700::1111")
    cfg = mp._build_config(p, "1.2.3.4:443", 1, "h2", "en0")
    assert cfg["outbounds"][0]["settings"]["remoteDNS"] == ["1.1.1.1", "2606:4700:4700::1111"]
    with pytest.raises(ValueError):
        mp._build_config(_profile(masque_remote_dns="dns.example.com"), "1.2.3.4:443", 1, "h2", "en0")


# -- auth rules (shared builder) ---------------------------------------------
def test_basic_auth_both_or_neither():
    p = _profile()
    ob = mp._build_config(p, "1.2.3.4:443", 1, "h2", "en0")["outbounds"][0]
    assert ob["streamSettings"]["masqueSettings"] == {}
    ob = mp._build_config(_profile(username="u", id="p"), "1.2.3.4:443", 1, "h2", "en0")["outbounds"][0]
    assert ob["streamSettings"]["masqueSettings"] == {"user": "u", "pass": "p"}


def test_warp_identity_complete_and_partial():
    full = _profile(masque_private_key="PRIV", masque_public_key="PUB",
                    masque_addresses="172.16.0.2/32, 2606:4700::2/128")
    ob = mp._build_config(full, "1.2.3.4:443", 1, "h2", "en0")["outbounds"][0]
    assert ob["streamSettings"]["masqueSettings"]["warp"] == {
        "privateKey": "PRIV", "publicKey": "PUB",
        "address": ["172.16.0.2/32", "2606:4700::2/128"]}
    # partial WARP identity: the profile itself is invalid
    assert not _profile(masque_private_key="PRIV", masque_public_key="PUB").is_valid()


def test_partial_basic_auth_rejected():
    # Both credentials or neither: a lone username/id is an invalid profile.
    assert not _profile(username="u").is_valid()
    assert not _profile(id="p").is_valid()
    assert _profile(username="u", id="p").is_valid()


# -- health url allowlist ----------------------------------------------------
def test_health_url_allowlist():
    assert mp._health_url_ok(mp.DEFAULT_HEALTH_URL)
    assert not mp._health_url_ok("http://www.google.com/generate_204")
    assert not mp._health_url_ok("https://evil.example.com/")
    assert not mp._health_url_ok("https://www.google.com.evil.com/")


# -- timeout validation ------------------------------------------------------
@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), True, "8", None])
def test_timeout_must_be_finite_positive(bad):
    with pytest.raises(ValueError):
        mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"), timeout=bad)
    with pytest.raises(ValueError):
        mp.scan_endpoints(_profile(), ["1.2.3.4:443"], xray_path=mp.Path("/x"), timeout=bad)


# -- fake process plumbing ---------------------------------------------------
class FakePopen:
    def __init__(self, args, **kw):
        self.args = args
        self.kw = kw
        self.terminated = False
        self.killed = False
        self.waited = 0
        FakePopen.instances.append(self)

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited += 1


def _run_probe(monkeypatch, profile, *, wait_state="ready", request=(12.0, None),
               cancel=None, timeout=8.0, iface="en0"):
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: wait_state)
    monkeypatch.setattr(mp, "_request", lambda *a, **k: (request[0], request[1], None))
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    res = mp.probe_endpoint(profile, xray_path=mp.Path("/xray"), timeout=timeout,
                            cancel_event=cancel, iface_alias=iface)
    return res, FakePopen.instances


def test_probe_success(monkeypatch):
    res, pops = _run_probe(monkeypatch, _profile(), request=(12.5, None))
    assert res.ok is True
    assert res.latency_ms == 12.5
    assert res.error == ""
    assert res.http_version == "h2"
    assert res.endpoint == "1.2.3.4:443"
    # own process always stopped
    assert len(pops) == 1 and pops[0].terminated


def test_probe_bad_response_not_ok(monkeypatch):
    # A real HTTP error status is a data-plane answer, not success.
    res, _ = _run_probe(monkeypatch, _profile(), request=(None, "HTTP 500"))
    assert res.ok is False and res.latency_ms is None and res.error == "HTTP 500"


def test_probe_tls_only_is_not_success(monkeypatch):
    # Handshake completed but the request itself failed -> not ok.
    res, _ = _run_probe(monkeypatch, _profile(), request=(None, "timeout"))
    assert res.ok is False and res.error == "timeout"


def test_probe_startup_timeout(monkeypatch):
    res, pops = _run_probe(monkeypatch, _profile(), wait_state="timeout")
    assert res.ok is False and res.error == "startup timeout"
    assert pops[0].terminated


def test_probe_xray_exited(monkeypatch):
    res, _ = _run_probe(monkeypatch, _profile(), wait_state="exited")
    assert res.ok is False and res.error == "xray exited"


def test_probe_cancel_before(monkeypatch):
    # pre-set cancel: no process spawned at all
    ev = threading.Event()
    ev.set()
    res, pops = _run_probe(monkeypatch, _profile(), cancel=ev)
    assert res.ok is False and res.error == "cancelled"
    assert pops == []  # never started xray


def test_probe_cancel_during(monkeypatch):
    res, pops = _run_probe(monkeypatch, _profile(), wait_state="cancelled")
    assert res.ok is False and res.error == "cancelled"
    assert pops[0].terminated


def test_probe_cancel_at_success(monkeypatch):
    # Cancellation arriving while the request is in flight must beat success.
    ev = threading.Event()

    def request(port, url, timeout, cancel_event=None):
        ev.set()
        return 12.0, None, None

    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp, "_request", request)
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"), cancel_event=ev,
                            iface_alias="en0")
    assert res.ok is False and res.error == "cancelled"
    assert res.latency_ms is None
    assert FakePopen.instances[0].terminated


class _FakeProxy:
    """Loopback proxy that holds (or trickles) the connection until terminated."""

    def __init__(self, trickle: bool = False):
        self.trickle = trickle
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.conns = []
        self._stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.conns.append(conn)
            if self.trickle:
                # One byte, then nothing: a per-read timeout would never fire.
                try:
                    conn.sendall(b"1")
                except OSError:
                    pass

    def terminate(self):
        self._stop.set()
        for c in self.conns:
            try:
                c.close()
            except OSError:
                pass


def test_probe_cancel_while_request_blocked(monkeypatch):
    # Real _request, blocked on a held socket: cancel must abort promptly,
    # kill only our own Xray (closing the proxy socket) and join the worker.
    proxy = _FakeProxy()
    ev = threading.Event()
    threading.Timer(0.05, ev.set).start()  # cancellation arrives mid-request

    class Popen(FakePopen):
        def terminate(self):
            super().terminate()
            proxy.terminate()

    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: proxy.port)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp.subprocess, "Popen", Popen)
    before = {t for t in threading.enumerate()}
    start = time.monotonic()
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"),
                            cancel_event=ev, timeout=8.0, iface_alias="en0")
    elapsed = time.monotonic() - start
    assert res.ok is False and res.error == "cancelled"
    assert elapsed < 1.0  # prompt, not at the 8s timeout
    assert FakePopen.instances[0].terminated
    # the request worker was joined: no new thread left behind
    assert {t for t in threading.enumerate()} - before == set()


def test_probe_request_deadline_trickle(monkeypatch):
    # Real _request against a trickling proxy: the whole-probe deadline must
    # end it, not a per-read socket timeout.
    proxy = _FakeProxy(trickle=True)

    class Popen(FakePopen):
        def terminate(self):
            super().terminate()
            proxy.terminate()

    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: proxy.port)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp.subprocess, "Popen", Popen)
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"), timeout=0.3,
                            iface_alias="en0")
    assert res.ok is False and res.error == "timeout"
    assert FakePopen.instances[0].terminated


def test_probe_popen_failure_is_sanitized(monkeypatch):
    def boom(*a, **k):
        raise OSError("xray: /secret/path with token=abc: no such file")

    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp.subprocess, "Popen", boom)
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"), iface_alias="en0")
    assert res.ok is False and res.error == "xray failed to start"
    assert "token" not in res.error and "secret" not in res.error


def test_probe_stop_wait_oserror_still_cleans(monkeypatch):
    # A child whose wait() raises (already reaped) must not leak the temp dir
    # or escape probe_endpoint: cleanup always runs.
    import tempfile

    class Popen(FakePopen):
        def wait(self, timeout=None):
            raise OSError("no child processes")

    created = []
    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp_spy(*a, **k):
        p = real_mkdtemp(*a, **k)
        created.append(p)
        return p

    FakePopen.instances = []
    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp_spy)
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp, "_request", lambda *a, **k: (5.0, None, None))
    monkeypatch.setattr(mp.subprocess, "Popen", Popen)
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"), iface_alias="en0")
    assert res.ok is True
    assert FakePopen.instances[0].terminated
    # the temp config dir was removed despite wait() raising
    assert created and not Path(created[0]).exists()


def test_probe_empty_iface_rejected(monkeypatch):
    # Empty/whitespace iface must fail clearly, not silently drop the binding.
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    for bad in ("", "   ", "\t"):
        res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"),
                                iface_alias=bad)
        assert res.ok is False and res.error == "no active internet interface"
    assert FakePopen.instances == []


def test_probe_deadline_expired_before_request(monkeypatch):
    # If startup eats the whole deadline, do not start a request at all.
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)

    def wait_ready(popen, port, deadline, cancel):
        time.sleep(0.2)  # consume the 0.1s budget
        return "ready"

    requests = []
    monkeypatch.setattr(mp, "_wait_ready", wait_ready)
    monkeypatch.setattr(mp, "_request",
                        lambda *a, **k: requests.append(1) or (5.0, None, None))
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"),
                            timeout=0.1, iface_alias="en0")
    assert res.ok is False and res.error == "timeout"
    assert requests == []  # never dialed
    assert FakePopen.instances[0].terminated


def test_probe_endpoint_sanitized(monkeypatch):
    # probe_endpoint (not just scan) must not raise on an unexpected error.
    def boom(profile, endpoint, **kw):
        raise RuntimeError("secret token leaked")

    monkeypatch.setattr(mp, "_probe_one", boom)
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"), iface_alias="en0")
    assert res.ok is False and res.error == "probe error"
    assert "secret" not in res.error


def test_request_once_closes_httperror(monkeypatch):
    # The HTTPError response object must be closed to release its socket.
    import urllib.error

    closed = []

    class FakeHTTPError(urllib.error.HTTPError):
        def __init__(self, url, code):
            super().__init__(url, code, "msg", None, None)
        def close(self):
            closed.append(True)

    def opener_open(url, timeout=None):
        raise FakeHTTPError(url, 500)

    monkeypatch.setattr(mp.urllib.request, "build_opener",
                        lambda *a, **k: type("O", (), {"open": staticmethod(opener_open)})())
    ms, err = mp._request_once(12345, "https://www.google.com/generate_204", 1.0)
    assert ms is None and err == "HTTP 500"
    assert closed == [True]


def test_probe_invalid_profile_settings(monkeypatch):
    # Partial WARP identity: is_valid() is False -> sanitized failure, no process.
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    p = _profile(masque_private_key="PRIV", masque_public_key="PUB")
    assert not p.is_valid()
    res = mp.probe_endpoint(p, xray_path=mp.Path("/xray"), iface_alias="en0")
    assert res.ok is False and res.error == "invalid profile settings"
    assert FakePopen.instances == []


def test_probe_requires_physical_iface(monkeypatch):
    # No iface alias: fail clearly instead of routing through our own TUN.
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"), iface_alias=None)
    assert res.ok is False and res.error == "no active internet interface"
    assert FakePopen.instances == []


def test_probe_invalid_version(monkeypatch):
    res, pops = _run_probe(monkeypatch, _profile(masque_http_version="h1"))
    assert res.ok is False and "invalid http version" in res.error
    assert pops == []


def test_probe_disallowed_health_url(monkeypatch):
    FakePopen.instances = []
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"),
                            health_url="https://evil.example.com/", iface_alias="en0")
    assert res.ok is False and "disallowed health url" in res.error
    assert FakePopen.instances == []


def test_probe_does_not_mutate_profile():
    p = _profile()
    before = vars(p)
    # call with a cancel already set so no process is spawned
    ev = threading.Event()
    ev.set()
    mp.probe_endpoint(p, xray_path=mp.Path("/xray"), cancel_event=ev, iface_alias="en0")
    assert vars(p) == before


def test_probe_config_secret_mode_and_devnull(monkeypatch):
    # The temp config holds credentials: 0600, and the child gets no disk log.
    import stat as _stat

    modes = []
    real_write = mp._write_secret

    def spy(path, text):
        real_write(path, text)
        modes.append(_stat.S_IMODE(path.stat().st_mode))

    cfgs = []

    def popen_spy(args, **kw):
        cfgs.append(json.loads(Path(args[args.index("-c") + 1]).read_text(encoding="utf-8")))
        return FakePopen(args, **kw)

    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp, "_request", lambda *a, **k: (5.0, None, None))
    monkeypatch.setattr(mp.subprocess, "Popen", popen_spy)
    monkeypatch.setattr(mp, "_write_secret", spy)
    p = _profile(username="u", id="p")
    res = mp.probe_endpoint(p, xray_path=mp.Path("/xray"), iface_alias="en0")
    assert res.ok is True
    pop = FakePopen.instances[0]
    assert pop.kw["stdout"] == subprocess.DEVNULL
    assert pop.kw["stderr"] == subprocess.DEVNULL
    assert cfgs[0]["outbounds"][0]["streamSettings"]["masqueSettings"] == {"user": "u", "pass": "p"}
    # the config file itself was 0600 while it existed
    assert modes == [0o600]


def _start_fake_proxy():
    """Loopback CONNECT proxy: tunnels to a local TLS server answering 204."""
    import ssl
    import subprocess as _sp
    import tempfile

    # Ephemeral dummy cert for the loopback fixture only.
    with tempfile.TemporaryDirectory() as d:
        cert, key = str(Path(d) / "c.pem"), str(Path(d) / "k.pem")
        _sp.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", key, "-out", cert, "-days", "1",
                 "-subj", "/CN=www.google.com"],
                check=True, capture_output=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    port = server.getsockname()[1]
    hits = {"n": 0}

    def serve():
        while True:
            try:
                conn, _ = server.accept()
                line = conn.recv(1024)
                if not line.startswith(b"CONNECT"):
                    conn.close()
                    continue
                hits["n"] += 1
                conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                tls = ctx.wrap_socket(conn, server_side=True)
                tls.recv(4096)
                tls.sendall(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
                tls.close()
            except OSError:
                return

    threading.Thread(target=serve, daemon=True).start()
    return port, hits, server


def test_probe_no_env_proxy_bypass(monkeypatch):
    # NO_PROXY/http_proxy must not reroute the probe away from our own proxy.
    import ssl

    port, hits, server = _start_fake_proxy()
    try:
        # The loopback fixture serves a dummy self-signed cert; trust it.
        monkeypatch.setattr(ssl, "_create_default_https_context",
                            ssl._create_unverified_context)
        monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
        monkeypatch.setenv("https_proxy", "http://127.0.0.1:1")
        monkeypatch.setenv("NO_PROXY", "www.google.com")
        monkeypatch.setattr(mp, "_free_port", lambda: port)
        monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
        monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
        res = mp.probe_endpoint(_profile(), xray_path=mp.Path("/xray"),
                                iface_alias="en0",
                                health_url="https://www.google.com/generate_204")
        assert res.ok is True and res.latency_ms is not None
        assert hits["n"] == 1  # the request went through OUR proxy
    finally:
        server.close()


# -- scan_endpoints bounds ---------------------------------------------------
def test_scan_rejects_bad_max_workers(monkeypatch):
    with pytest.raises(ValueError):
        mp.scan_endpoints(_profile(), ["1.2.3.4:443"], xray_path=mp.Path("/x"),
                          max_workers=0)
    with pytest.raises(ValueError):
        mp.scan_endpoints(_profile(), ["1.2.3.4:443"], xray_path=mp.Path("/x"),
                          max_workers=6)


def test_scan_rejects_too_many_endpoints(monkeypatch):
    eps = [f"10.0.0.{i}:443" for i in range(mp.MAX_ENDPOINTS + 1)]
    with pytest.raises(ValueError):
        mp.scan_endpoints(_profile(), eps, xray_path=mp.Path("/x"))


def test_scan_bounds_constants():
    assert mp.MAX_ENDPOINTS == 64
    assert mp.MAX_WORKERS == 5


def test_scan_runs_each_endpoint_and_stops_processes(monkeypatch):
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp, "_request", lambda *a, **k: (5.0, None, None))
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    eps = ["1.1.1.1:443", "2.2.2.2:443", "3.3.3.3:443"]
    results = mp.scan_endpoints(_profile(), eps, xray_path=mp.Path("/x"),
                                max_workers=3, iface_alias="en0")
    assert [r.endpoint for r in results] == eps  # input order preserved
    assert all(r.ok for r in results)
    assert len(FakePopen.instances) == 3
    assert all(p.terminated for p in FakePopen.instances)


def test_scan_malformed_endpoint_reports_not_raises(monkeypatch):
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp, "_request", lambda *a, **k: (5.0, None, None))
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    results = mp.scan_endpoints(_profile(), ["1.1.1.1:443", "bad-endpoint"],
                                xray_path=mp.Path("/x"), iface_alias="en0")
    assert results[0].ok is True
    assert results[1].ok is False and "invalid endpoint" in results[1].error


def test_scan_invalid_profile_among_valid(monkeypatch):
    # One broken profile must not abort the scan of the other endpoints.
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp, "_wait_ready", lambda *a, **k: "ready")
    monkeypatch.setattr(mp, "_request", lambda *a, **k: (5.0, None, None))
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    broken = _profile(masque_private_key="PRIV")  # partial WARP: is_valid() False
    results = mp.scan_endpoints(broken, ["1.1.1.1:443", "2.2.2.2:443"],
                                xray_path=mp.Path("/x"), iface_alias="en0")
    assert [r.ok for r in results] == [False, False]
    assert all(r.error == "invalid profile settings" for r in results)
    assert FakePopen.instances == []


def test_scan_cancel_prevents_queued_work(monkeypatch):
    # Cancel before the scan: nothing is spawned, every endpoint reported.
    FakePopen.instances = []
    monkeypatch.setattr(mp, "_free_port", lambda: 12345)
    monkeypatch.setattr(mp.subprocess, "Popen", FakePopen)
    ev = threading.Event()
    ev.set()
    eps = ["1.1.1.1:443", "2.2.2.2:443", "3.3.3.3:443"]
    results = mp.scan_endpoints(_profile(), eps, xray_path=mp.Path("/x"),
                                cancel_event=ev, iface_alias="en0")
    assert [r.endpoint for r in results] == eps
    assert all(r.ok is False and r.error == "cancelled" for r in results)
    assert FakePopen.instances == []


def test_scan_exception_in_one_endpoint_keeps_others(monkeypatch):
    # A raised probe must not abort the scan; the error is sanitized.
    def boom(profile, endpoint, **kw):
        raise RuntimeError("secret token leaked")

    monkeypatch.setattr(mp, "_probe_one", boom)
    results = mp.scan_endpoints(_profile(), ["1.1.1.1:443", "2.2.2.2:443"],
                                xray_path=mp.Path("/x"), iface_alias="en0")
    assert [r.ok for r in results] == [False, False]
    assert all(r.error == "probe error" for r in results)
    assert all("secret" not in r.error for r in results)
