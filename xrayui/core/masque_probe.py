"""Bounded MASQUE endpoint probing.

Starts an isolated throwaway Xray process with one local HTTP inbound and one
MASQUE outbound, then drives a real HTTPS request through that tunnel to a
fixed health URL. A TLS handshake alone is not success: the probe only reports
ok when a real HTTP response came back over the data plane. The process is
always terminated on every path. This module is Qt-free.
"""
from __future__ import annotations

import ipaddress
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from . import geo_exit, proc

# A probe is one throwaway Xray per endpoint; cap how many endpoints and how
# many concurrent Xray processes a single scan may spawn.
MAX_ENDPOINTS = 64
MAX_WORKERS = 5

# The only health URL the probe will dial through the tunnel. Fixed and
# allowlisted so a scan can never be pointed at an arbitrary host.
DEFAULT_HEALTH_URL = "https://www.google.com/generate_204"
_ALLOWED_HEALTH_HOSTS = frozenset({"www.google.com"})

_MAX_BODY = 4096
_CONFIG_NAME = "masque_probe.json"
_LOG_NAME = "masque_probe.log"

_VERSIONS = ("h2", "h3")


@dataclass(frozen=True)
class ProbeResult:
    endpoint: str
    http_version: str
    ok: bool
    latency_ms: float | None
    error: str


def parse_endpoint(endpoint: str) -> tuple[str, int]:
    """Split "host:port" (or "[v6]:port") into (host, port). Raises ValueError."""
    if not isinstance(endpoint, str) or not endpoint:
        raise ValueError("empty endpoint")
    if endpoint.startswith("["):
        close = endpoint.find("]")
        if close == -1 or not endpoint[close + 1:close + 2] == ":":
            raise ValueError("bad IPv6 endpoint")
        host = endpoint[1:close]
        port = endpoint[close + 2:]
    else:
        host, sep, port = endpoint.rpartition(":")
        if not sep:
            raise ValueError("missing port")
    if not host:
        raise ValueError("empty host")
    try:
        portnum = int(port)
    except ValueError:
        raise ValueError("bad port") from None
    if not 1 <= portnum <= 65535:
        raise ValueError("port out of range")
    return host, portnum


def _http_version(profile) -> str:
    return (getattr(profile, "masque_http_version", "") or "h2").strip().lower()


def _split(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[,\n]", text or "") if s.strip()]


def _health_url_ok(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and parts.hostname in _ALLOWED_HEALTH_HOSTS


def _masque_settings(p) -> dict:
    ms: dict = {}
    if p.host:
        ms["host"] = p.host
    if p.path:
        ms["path"] = p.path
    user, pw = p.username, p.id
    warp = getattr(p, "masque_private_key", "") or getattr(p, "masque_public_key", "") \
        or getattr(p, "masque_addresses", "")
    if warp and (user or pw):
        # WARP identity and basic auth are mutually exclusive in Xray.
        raise ValueError("WARP identity and basic auth are mutually exclusive")
    if user or pw:
        if not (user and pw):
            raise ValueError("partial basic auth")
        ms["user"] = user
        ms["pass"] = pw
    if warp:
        priv = getattr(p, "masque_private_key", "")
        pub = getattr(p, "masque_public_key", "")
        addrs = _split(getattr(p, "masque_addresses", ""))
        if not (priv and pub and addrs):
            raise ValueError("partial WARP identity")
        ms["warp"] = {"privateKey": priv, "publicKey": pub, "address": addrs}
    return ms


def _tls_settings(p, version: str) -> dict:
    tls: dict = {}
    if p.sni:
        tls["serverName"] = p.sni
    if p.fp:
        tls["fingerprint"] = p.fp
    # A single carrier: the negotiated ALPN is what selects h2 vs h3.
    tls["alpn"] = [version]
    if p.pcs:
        from .profiles import normalize_pcs
        tls["pinnedPeerCertSha256"] = normalize_pcs(p.pcs)
    if p.vcn:
        tls["verifyPeerCertByName"] = p.vcn
    return tls


def _build_config(p, endpoint: str, port: int, version: str) -> dict:
    host, portnum = parse_endpoint(endpoint)
    settings: dict = {"address": host, "port": portnum}
    rdns = _split(getattr(p, "masque_remote_dns", ""))
    if rdns:
        for ip in rdns:
            ipaddress.ip_address(ip)  # remoteDNS must be literal IPs
        settings["remoteDNS"] = rdns
    outbound = {
        "tag": "out",
        "protocol": "masque",
        "settings": settings,
        "streamSettings": {
            "method": "masque",
            "security": "tls",
            "masqueSettings": _masque_settings(p),
            "tlsSettings": _tls_settings(p, version),
        },
    }
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"tag": "in", "listen": "127.0.0.1", "port": port,
                      "protocol": "http", "settings": {}}],
        "outbounds": [outbound],
        "routing": {"domainStrategy": "IPOnDemand",
                    "rules": [{"type": "field", "inboundTag": ["in"],
                               "outboundTag": "out"}]},
    }


def _free_port() -> int:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _port_open(port: int) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _wait_ready(popen, port: int, deadline: float, cancel: threading.Event | None) -> str:
    """'ready', 'exited', 'timeout' or 'cancelled'."""
    while time.monotonic() < deadline:
        if cancel is not None and cancel.is_set():
            return "cancelled"
        if popen.poll() is not None:
            return "exited"
        if _port_open(port):
            return "ready"
        time.sleep(0.05)
    return "timeout"


def _status_error(status: int) -> str | None:
    if status == 204 or 200 <= status < 300:
        return None
    if status == 503:
        # Xray's HTTP inbound answers 503 itself when the outbound could not
        # connect -- the target was never reached.
        return "connection failed"
    return f"HTTP {status}"


def _request(port: int, url: str, timeout: float) -> tuple[float | None, str | None]:
    """One real HTTPS GET through the local HTTP proxy. Returns (ms, error)."""
    proxy_url = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(
        geo_exit.ExplicitProxyHandler({"http": proxy_url, "https": proxy_url}))
    start = time.perf_counter()
    try:
        with opener.open(url, timeout=timeout) as resp:
            status = resp.status
            resp.read(_MAX_BODY)
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:  # noqa: BLE001 -- any failure means "not working"
        return None, str(e)
    elapsed_ms = (time.perf_counter() - start) * 1000
    error = _status_error(status)
    return (None if error else elapsed_ms), error


def _stop(popen) -> None:
    popen.terminate()
    try:
        popen.wait(timeout=3)
    except subprocess.TimeoutExpired:
        popen.kill()
        try:
            popen.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def _probe_one(profile, endpoint: str, *, xray_path: Path, timeout: float,
               cancel_event: threading.Event | None, health_url: str) -> ProbeResult:
    version = _http_version(profile)
    if version not in _VERSIONS:
        return ProbeResult(endpoint, version, False, None, "invalid http version")
    try:
        parse_endpoint(endpoint)
    except ValueError as e:
        return ProbeResult(endpoint, version, False, None, f"invalid endpoint: {e}")
    if not _health_url_ok(health_url):
        return ProbeResult(endpoint, version, False, None, "disallowed health url")
    if cancel_event is not None and cancel_event.is_set():
        return ProbeResult(endpoint, version, False, None, "cancelled")

    deadline = time.monotonic() + timeout
    port = _free_port()
    tmp = Path(tempfile.mkdtemp(prefix="masque-probe-"))
    cfg_path = tmp / _CONFIG_NAME
    log_path = tmp / _LOG_NAME
    popen = None
    try:
        cfg_path.write_text(json.dumps(_build_config(profile, endpoint, port, version)),
                            encoding="utf-8")
        env = proc.child_env({"XRAY_LOCATION_ASSET": str(paths.asset_dir())})
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            popen = subprocess.Popen(
                [str(xray_path), "run", "-c", str(cfg_path)],
                stdout=log, stderr=subprocess.STDOUT, cwd=str(paths.base_dir()),
                env=env, creationflags=proc.CREATE_NO_WINDOW,
                startupinfo=proc._startupinfo())
            state = _wait_ready(popen, port, deadline, cancel_event)
            if state != "ready":
                return ProbeResult(endpoint, version, False, None,
                                   {"exited": "xray exited", "timeout": "startup timeout",
                                    "cancelled": "cancelled"}[state])
            remaining = max(0.1, deadline - time.monotonic())
            latency, error = _request(port, health_url, remaining)
            if error:
                return ProbeResult(endpoint, version, False, None, error)
            return ProbeResult(endpoint, version, True, latency, "")
    finally:
        if popen is not None:
            _stop(popen)
        shutil.rmtree(tmp, ignore_errors=True)


def probe_endpoint(profile, *, xray_path: Path, timeout: float = 8.0,
                   cancel_event: threading.Event | None = None,
                   health_url: str = DEFAULT_HEALTH_URL) -> ProbeResult:
    """Probe the profile's own endpoint through an isolated Xray tunnel."""
    endpoint = f"{profile.address}:{profile.port}"
    return _probe_one(profile, endpoint, xray_path=xray_path, timeout=timeout,
                      cancel_event=cancel_event, health_url=health_url)


def scan_endpoints(profile, endpoints, *, xray_path: Path, timeout: float = 8.0,
                   max_workers: int = 2, cancel_event: threading.Event | None = None,
                   health_url: str = DEFAULT_HEALTH_URL) -> list[ProbeResult]:
    """Probe each endpoint with at most `max_workers` concurrent Xray processes."""
    if not 1 <= max_workers <= MAX_WORKERS:
        raise ValueError(f"max_workers must be 1..{MAX_WORKERS}")
    if len(endpoints) > MAX_ENDPOINTS:
        raise ValueError(f"too many endpoints (max {MAX_ENDPOINTS})")
    results: list[ProbeResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_probe_one, profile, ep, xray_path=xray_path,
                               timeout=timeout, cancel_event=cancel_event,
                               health_url=health_url) for ep in endpoints]
        for fut in as_completed(futures):
            results.append(fut.result())
    order = {ep: i for i, ep in enumerate(endpoints)}
    results.sort(key=lambda r: order[r.endpoint])
    return results
