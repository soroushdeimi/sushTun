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
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from . import geo_exit, outbounds, proc

# A probe is one throwaway Xray per endpoint; cap how many endpoints and how
# many concurrent Xray processes a single scan may spawn.
MAX_ENDPOINTS = 64
MAX_WORKERS = 5

# The only health URL the probe will dial through the tunnel. Fixed and
# allowlisted so a scan can never be pointed at an arbitrary host.
DEFAULT_HEALTH_URL = "https://www.google.com/generate_204"
_ALLOWED_HEALTH_HOSTS = frozenset({"www.google.com"})

_MAX_BODY = 4096
_MAX_TIMEOUT = 300.0
# The worker's socket timeout is a backstop; the whole-probe deadline is
# authoritative, so it must fire first. This slack keeps the two from racing.
_REQUEST_SLACK = 0.5
_CONFIG_NAME = "masque_probe.json"

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


def _check_timeout(timeout) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a number")
    if not math.isfinite(timeout) or not 0 < timeout <= _MAX_TIMEOUT:
        raise ValueError(f"timeout must be finite, > 0 and <= {_MAX_TIMEOUT}s")


def _health_url_ok(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and parts.hostname in _ALLOWED_HEALTH_HOSTS


def _build_config(p, endpoint: str, port: int, version: str,
                  iface_alias: str | None = None) -> dict:
    host, portnum = parse_endpoint(endpoint)
    outbound = outbounds.build(p, "out")
    outbound["settings"]["address"] = host
    outbound["settings"]["port"] = portnum
    # The probe picks the version explicitly; the builder uses the profile's.
    outbound["streamSettings"]["tlsSettings"]["alpn"] = [version]
    for ip in outbound["settings"].get("remoteDNS", []):
        ipaddress.ip_address(ip)  # remoteDNS must be literal IPs
    sockopt = outbound["streamSettings"].get("sockopt")
    if sockopt is not None:
        if iface_alias:
            sockopt["interface"] = iface_alias
        else:
            del sockopt["interface"]
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


def _request_once(port: int, url: str, timeout: float) -> tuple[float | None, str | None]:
    """One real HTTPS GET through the local HTTP proxy. Returns (ms, error)."""
    proxy_url = f"http://127.0.0.1:{port}"
    opener = geo_exit.build_opener(proxy_url)
    start = time.perf_counter()
    try:
        with opener.open(url, timeout=timeout) as resp:
            status = resp.status
            resp.read(_MAX_BODY)
    except urllib.error.HTTPError as e:
        status = e.code
        e.close()  # release the socket behind the error response
    except TimeoutError:
        return None, "timeout"
    except Exception:
        # Connection refused, DNS failure, TLS error: all just mean "this
        # endpoint did not work"; the raw text is not shown to the user.
        return None, "request failed"
    elapsed_ms = (time.perf_counter() - start) * 1000
    error = _status_error(status)
    return (None if error else elapsed_ms), error


def _request(port: int, url: str, timeout: float,
             cancel_event: threading.Event | None = None) -> tuple[float | None, str | None, threading.Thread]:
    """A request bounded by the whole-probe deadline and by cancellation.

    Returns (ms, error, worker thread). The worker is a daemon that only
    finishes once the proxy socket dies, so the caller must stop its own Xray
    on abort/timeout and then join the worker: no orphan threads.
    """
    box: dict = {}

    def worker():
        # Slack keeps the worker's socket timeout behind the deadline, so a
        # trickled connection ends as "timeout", not a raw socket error.
        box["res"] = _request_once(port, url, timeout + _REQUEST_SLACK)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    end = time.monotonic() + timeout
    while t.is_alive():
        if cancel_event is not None and cancel_event.is_set():
            return None, "cancelled", t
        if time.monotonic() >= end:
            return None, "timeout", t
        t.join(min(0.05, max(0.0, end - time.monotonic())))
    return box["res"][0], box["res"][1], t


def _stop(popen) -> None:
    # Never raises: the child may already be gone/reaped, and cleanup must
    # continue (join the request worker, remove the temp dir) on every path.
    try:
        popen.terminate()
    except OSError:
        pass  # already gone
    try:
        popen.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            popen.kill()
        except OSError:
            pass
        try:
            popen.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            pass
    except OSError:
        pass  # already reaped


def _write_secret(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def _probe_one(profile, endpoint: str, *, xray_path: Path, timeout: float,
               cancel_event: threading.Event | None, health_url: str,
               iface_alias: str | None) -> ProbeResult:
    version = _http_version(profile)
    if version not in _VERSIONS:
        return ProbeResult(endpoint, version, False, None, "invalid http version")
    try:
        parse_endpoint(endpoint)
    except ValueError as e:
        return ProbeResult(endpoint, version, False, None, f"invalid endpoint: {e}")
    if not _health_url_ok(health_url):
        return ProbeResult(endpoint, version, False, None, "disallowed health url")
    if not (isinstance(iface_alias, str) and iface_alias.strip()):
        # Without a real physical interface the outbound would ride our own
        # TUN and the result would not be a direct reachability measurement.
        return ProbeResult(endpoint, version, False, None, "no active internet interface")
    if cancel_event is not None and cancel_event.is_set():
        return ProbeResult(endpoint, version, False, None, "cancelled")
    valid = getattr(profile, "is_valid", None)
    if callable(valid) and not valid():
        return ProbeResult(endpoint, version, False, None, "invalid profile settings")

    deadline = time.monotonic() + timeout
    port = _free_port()
    tmp = Path(tempfile.mkdtemp(prefix="masque-probe-"))
    cfg_path = tmp / _CONFIG_NAME
    popen = None
    worker = None
    try:
        try:
            _write_secret(cfg_path, json.dumps(_build_config(profile, endpoint, port,
                                                              version, iface_alias)))
        except Exception:
            return ProbeResult(endpoint, version, False, None, "invalid profile settings")
        env = proc.child_env({"XRAY_LOCATION_ASSET": str(paths.asset_dir())})
        try:
            # No child disk log: output is throwaway and DEVNULL keeps it bounded.
            popen = subprocess.Popen(
                [str(xray_path), "run", "-c", str(cfg_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                cwd=str(paths.base_dir()), env=env,
                creationflags=proc.CREATE_NO_WINDOW,
                startupinfo=proc._startupinfo())
        except Exception:
            return ProbeResult(endpoint, version, False, None, "xray failed to start")
        state = _wait_ready(popen, port, deadline, cancel_event)
        if state != "ready":
            return ProbeResult(endpoint, version, False, None,
                               {"exited": "xray exited", "timeout": "startup timeout",
                                "cancelled": "cancelled"}[state])
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # The whole-probe deadline already passed during startup.
            return ProbeResult(endpoint, version, False, None, "timeout")
        latency, error, worker = _request(port, health_url, remaining, cancel_event)
        # Cancellation arriving while the request was in flight wins over success.
        if cancel_event is not None and cancel_event.is_set():
            return ProbeResult(endpoint, version, False, None, "cancelled")
        if error:
            return ProbeResult(endpoint, version, False, None, error)
        return ProbeResult(endpoint, version, True, latency, "")
    finally:
        if popen is not None:
            try:
                _stop(popen)
            except Exception:
                pass  # never let cleanup of the child block the rest
        if worker is not None:
            worker.join(3)  # the stopped proxy unblocks the request socket
        shutil.rmtree(tmp, ignore_errors=True)


def _safe_probe(profile, endpoint: str, **kw) -> ProbeResult:
    # A scan must never abort because one endpoint raised.
    try:
        return _probe_one(profile, endpoint, **kw)
    except Exception:
        return ProbeResult(endpoint, _http_version(profile), False, None, "probe error")


def probe_endpoint(profile, *, xray_path: Path, timeout: float = 8.0,
                   cancel_event: threading.Event | None = None,
                   health_url: str = DEFAULT_HEALTH_URL,
                   iface_alias: str | None = None) -> ProbeResult:
    """Probe the profile's own endpoint through an isolated Xray tunnel.

    `iface_alias` pins the outbound to the physical interface (speedtest
    convention) so probing works while the app's TUN is active; None is a
    clear failure, never a silent route through our own tunnel.
    """
    _check_timeout(timeout)
    endpoint = f"{profile.address}:{profile.port}"
    return _safe_probe(profile, endpoint, xray_path=xray_path, timeout=timeout,
                       cancel_event=cancel_event, health_url=health_url,
                       iface_alias=iface_alias)


def scan_endpoints(profile, endpoints, *, xray_path: Path, timeout: float = 8.0,
                   max_workers: int = 2, cancel_event: threading.Event | None = None,
                   health_url: str = DEFAULT_HEALTH_URL,
                   iface_alias: str | None = None) -> list[ProbeResult]:
    """Probe each endpoint with at most `max_workers` concurrent Xray processes."""
    _check_timeout(timeout)
    if not 1 <= max_workers <= MAX_WORKERS:
        raise ValueError(f"max_workers must be 1..{MAX_WORKERS}")
    if len(endpoints) > MAX_ENDPOINTS:
        raise ValueError(f"too many endpoints (max {MAX_ENDPOINTS})")
    results: list[ProbeResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = []
        for ep in endpoints:
            if cancel_event is not None and cancel_event.is_set():
                # Cancelled before it was queued: report, do not start.
                results.append(ProbeResult(ep, _http_version(profile), False, None,
                                           "cancelled"))
                continue
            futures.append(pool.submit(_safe_probe, profile, ep, xray_path=xray_path,
                                       timeout=timeout, cancel_event=cancel_event,
                                       health_url=health_url, iface_alias=iface_alias))
        for fut in as_completed(futures):
            results.append(fut.result())
    order = {ep: i for i, ep in enumerate(endpoints)}
    results.sort(key=lambda r: order[r.endpoint])
    return results
