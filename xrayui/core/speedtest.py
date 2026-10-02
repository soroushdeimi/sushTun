"""Real-delay and TCP-ping testing for a batch of profiles.

Runs its own throwaway Xray process against a config with one HTTP inbound
per profile, bound to the physical interface so testing works while the
tunnel is up. Never touches the live connection's process, config or log.
"""
from __future__ import annotations

import functools
import http.client
import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import paths
from . import coreopts, geo_exit, metrics, outbounds, proc
from .profiles import Profile

OnResult = Callable[[str, "float | None", "str | None"], None]
OnDetail = Callable[[str, dict], None]
RunBatch = Callable[..., bool]

_CONFIG_NAME = "speedtest.json"
_LOG_NAME = "speedtest.log"

# A skip isn't a failure: the profile was never dialed at all, so it's wrong
# to show it (or count it in Remove failed) the same way as a real timeout.
# The reason string still travels through the normal on_result(uid, None,
# reason) contract; is_skipped() is the one place that recognizes which
# reasons mean "skipped" so callers never have to string-match themselves.
SKIP_UNAVAILABLE_WHILE_CONNECTED = "unavailable while connected"
SKIP_UDP = "n/a (UDP)"
SKIP_REASONS = frozenset({SKIP_UNAVAILABLE_WHILE_CONNECTED, SKIP_UDP})


def is_skipped(error: str | None) -> bool:
    return error in SKIP_REASONS


def build_test_config(
    profiles: list[Profile], ports: list[int], iface_alias: str, core_cfg: dict | None = None,
) -> dict:
    """A from-scratch Xray config: one HTTP inbound + outbound pair per profile.

    No tun inbound, no dns-in, no stats API -- this never touches the ports
    or tags the live connection owns, so it can run concurrently with it.
    core_cfg, when given, applies TLS fragment and UDP noise the same way
    render.build_text does -- a server that only works with them enabled must
    not show up as failed just because the test dialed it without.
    """
    inbounds = []
    outbounds_list = []
    rules = []
    for p, port in zip(profiles, ports, strict=True):
        in_tag = f"in-{p.uid}"
        out_tag = f"out-{p.uid}"
        inbounds.append({
            "tag": in_tag,
            "listen": "127.0.0.1",
            "port": port,
            "protocol": "http",
            "settings": {},
        })
        outbound = outbounds.build(p, out_tag)
        if core_cfg:
            coreopts.apply_fragment({"outbounds": [outbound]}, core_cfg, p)
            coreopts.apply_udp_noise({"outbounds": [outbound]}, core_cfg, p)
        outbounds_list.append(outbound)
        rules.append({"type": "field", "inboundTag": [in_tag], "outboundTag": out_tag})

    cfg = {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": outbounds_list,
        "routing": {"domainStrategy": "IPOnDemand", "rules": rules},
    }
    # Same trick as render.build_text: substitute after serializing, so every
    # nested sockopt.interface placeholder is replaced in one pass.
    text = json.dumps(cfg)
    text = text.replace("__INTERFACE__", iface_alias).replace("__IFACE__", iface_alias)
    return json.loads(text)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _wait_ready(popen: subprocess.Popen, ports: list[int], deadline: float) -> bool:
    while time.monotonic() < deadline:
        if popen.poll() is not None:
            return False  # exited before opening its ports: a bad config
        if all(_port_open(port) for port in ports):
            return True
        time.sleep(0.05)
    return False


def _last_log_line() -> str:
    log_path = paths.state_dir() / _LOG_NAME
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "no log output"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else "no log output"


def _short_config_error() -> str:
    # Xray's own error is one long " > "-joined chain of wrapped context
    # ("failed to load config files: [...] > infra/conf: ... > empty
    # \"password\""); only the last segment is the actual reason. The full
    # line is still in speedtest.log for anyone who needs the whole chain.
    return _last_log_line().rsplit(" > ", 1)[-1].strip()


class Measured(tuple):
    """(delay_ms, error), unpackable as a pair; `cold` is the first request's
    time when a warm measurement made two."""

    cold: float | None

    def __new__(cls, delay: float | None, error: str | None, cold: float | None = None):
        self = super().__new__(cls, (delay, error))
        self.cold = cold
        return self


MODES = ("warm", "cold")
_WARM_GAP_S = 0.1


def _status_error(status: int) -> str | None:
    if status == 204 or 200 <= status < 300:
        return None
    if status == 503:
        # Xray's HTTP inbound answers 503 itself when its outbound couldn't
        # connect -- the target was never reached, so this isn't the
        # target's answer at all.
        return "connection failed"
    return f"HTTP {status}"


def _measure_cold(port: int, url: str, timeout: float) -> Measured:
    proxy_url = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(
        geo_exit.ExplicitProxyHandler({"http": proxy_url, "https": proxy_url})
    )
    start = time.perf_counter()
    try:
        with opener.open(url, timeout=timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:
        # Connection refused (e.g. xray died mid-test -- see the Windows
        # image-name caveat below), DNS failure, TLS errors, timeouts: all
        # of it just means "this server didn't work", not a bug to raise
        # from a worker thread.
        return Measured(None, str(e))
    elapsed_ms = (time.perf_counter() - start) * 1000
    error = _status_error(status)
    return Measured(None if error else elapsed_ms, error)


def _measure_warm(port: int, url: str, timeout: float) -> Measured:
    """Two GETs on one kept-alive connection; the smaller time is the delay.

    The first request pays for the connection, the VLESS handshake and TLS to
    the target; the second only for the round trip, which is what other
    clients (v2rayN) report.
    """
    parts = urllib.parse.urlsplit(url)
    https = parts.scheme == "https"
    if https:
        conn = http.client.HTTPSConnection("127.0.0.1", port, timeout=timeout)
        conn.set_tunnel(parts.hostname, parts.port or 443)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
    else:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        target = url  # a proxy wants the absolute URL
    times: list[float] = []
    try:
        for attempt in range(2):
            if attempt:
                time.sleep(_WARM_GAP_S)
            start = time.perf_counter()
            conn.request("GET", target)
            resp = conn.getresponse()
            resp.read()
            elapsed_ms = (time.perf_counter() - start) * 1000
            error = _status_error(resp.status)
            if error:
                if attempt:
                    break  # the first one worked; keep it
                return Measured(None, error)
            times.append(elapsed_ms)
    except Exception as e:
        if not times:
            return Measured(None, str(e))
    finally:
        conn.close()
    return Measured(min(times), None, times[0])


def _measure_one(port: int, url: str, timeout: float, mode: str = "warm") -> Measured:
    if mode == "cold":
        return _measure_cold(port, url, timeout)
    return _measure_warm(port, url, timeout)


def _measure_group(
    profiles: list[Profile], ports: list[int], *,
    url: str, timeout: float, on_result: OnResult, cancel: threading.Event,
    mode: str = "warm", on_detail: OnDetail | None = None,
) -> None:
    def one(p: Profile, port: int) -> None:
        m = _measure_one(port, url, timeout, mode)
        delay, error = m
        on_result(p.uid, delay, error)
        if delay is None or on_detail is None:
            return
        fields = {"cold_ms": m.cold}
        info = geo_exit.detect(f"http://127.0.0.1:{port}", timeout)
        if info:
            fields.update(country=info.country, exit_ip=info.ip)
        on_detail(p.uid, fields)

    with ThreadPoolExecutor(max_workers=max(1, len(profiles))) as pool:
        futures = []
        for p, port in zip(profiles, ports, strict=True):
            if cancel.is_set():
                break
            futures.append(pool.submit(one, p, port))
        for fut in as_completed(futures):
            fut.result()


def _run_batch(
    profiles: list[Profile], ports: list[int], *,
    url: str, timeout: float, iface_alias: str, on_result: OnResult, cancel: threading.Event,
    core_cfg: dict | None = None, mode: str = "warm", on_detail: OnDetail | None = None,
) -> bool:
    """Start our own throwaway xray for this batch and measure it.

    Returns False if xray exited before opening its ports (a bad profile
    somewhere in the batch breaks the whole config) -- true even if every
    individual profile's HTTP test then failed, since that's reported per
    profile via on_result, not a batch failure.
    """
    paths.state_dir().mkdir(parents=True, exist_ok=True)
    config_path = paths.state_dir() / _CONFIG_NAME
    log_path = paths.state_dir() / _LOG_NAME

    cfg = build_test_config(profiles, ports, iface_alias, core_cfg=core_cfg)
    config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    # Our own Popen and log file: never XrayProcess (it truncates xray.log,
    # the live connection's log) and never paths.runtime_config() (the live
    # connection's config -- restarting it drops the tunnel).
    env = proc.child_env({"XRAY_LOCATION_ASSET": str(paths.asset_dir())})
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        popen = subprocess.Popen(
            [str(paths.xray_exe()), "run", "-c", str(config_path)],
            stdout=log, stderr=subprocess.STDOUT, cwd=str(paths.base_dir()), env=env,
            creationflags=proc.CREATE_NO_WINDOW, startupinfo=proc._startupinfo(),
        )
        try:
            if not _wait_ready(popen, ports, time.monotonic() + timeout):
                return False
            _measure_group(profiles, ports, url=url, timeout=timeout,
                            on_result=on_result, cancel=cancel,
                            mode=mode, on_detail=on_detail)
            return True
        finally:
            # NEVER xray._kill_all() / XrayProcess.stop() here: both match
            # by image name (Windows) or our own runtime config path and
            # would kill the user's live tunnel too. Only ever touch the
            # Popen this function itself started, and always -- on success,
            # on a bad config, on cancel, or on an exception from measuring.
            #
            # On Windows, is_xray_running()/_kill_all() also match by image
            # name (xray.exe) with no way to tell our test process from the
            # live one, so Connect/Disconnect during a test can kill this
            # Popen out from under us. _wait_ready and _measure_one both
            # already treat a dead/unreachable process as an ordinary
            # per-profile failure, so that surfaces as errors, not a crash.
            popen.terminate()
            try:
                popen.wait(timeout=3)
            except subprocess.TimeoutExpired:
                popen.kill()
                popen.wait(timeout=3)


def _test_group(
    profiles: list[Profile], on_result: OnResult, cancel: threading.Event, *,
    url: str, timeout: float, iface_alias: str, run_batch: RunBatch,
    core_cfg: dict | None = None,
) -> None:
    if cancel.is_set() or not profiles:
        return
    ports = [_free_port() for _ in profiles]
    ok = run_batch(profiles, ports, url=url, timeout=timeout, iface_alias=iface_alias,
                    on_result=on_result, cancel=cancel, core_cfg=core_cfg)
    if ok:
        return
    if len(profiles) == 1:
        on_result(profiles[0].uid, None, f"invalid config: {_short_config_error()}")
        return
    mid = len(profiles) // 2
    _test_group(profiles[:mid], on_result, cancel,
                url=url, timeout=timeout, iface_alias=iface_alias, run_batch=run_batch,
                core_cfg=core_cfg)
    if cancel.is_set():
        return
    _test_group(profiles[mid:], on_result, cancel,
                url=url, timeout=timeout, iface_alias=iface_alias, run_batch=run_batch,
                core_cfg=core_cfg)


def real_delay_all(
    profiles: list[Profile],
    on_result: OnResult,
    cancel: threading.Event,
    *,
    url: str,
    timeout: float = 10.0,
    batch_size: int = 50,
    iface_alias: str,
    connected: bool = False,
    run_batch: RunBatch | None = None,
    core_cfg: dict | None = None,
    mode: str = "warm",
    on_detail: OnDetail | None = None,
) -> None:
    # A custom run_batch keeps the plain contract; mode and details only
    # travel with the real one.
    run_batch = run_batch or functools.partial(_run_batch, mode=mode, on_detail=on_detail)

    testable: list[Profile] = []
    for p in profiles:
        if connected and (p.protocol or "").lower() == "wireguard":
            # A WireGuard outbound has no streamSettings/sockopt (Xray
            # rejects sockopt there), so it can't be pinned to the physical
            # interface. While the tunnel is up, its test traffic would loop
            # through our own TUN instead of leaving directly.
            on_result(p.uid, None, SKIP_UNAVAILABLE_WHILE_CONNECTED)
            continue
        testable.append(p)

    for i in range(0, len(testable), batch_size):
        if cancel.is_set():
            return
        _test_group(testable[i:i + batch_size], on_result, cancel,
                    url=url, timeout=timeout, iface_alias=iface_alias, run_batch=run_batch,
                    core_cfg=core_cfg)


_TCP_PING_UNAVAILABLE = frozenset({"wireguard", "hysteria2"})


def tcping_all(
    profiles: list[Profile], on_result: OnResult, cancel: threading.Event, workers: int = 16,
) -> None:
    def one(p: Profile) -> None:
        if (p.protocol or "").lower() in _TCP_PING_UNAVAILABLE:
            # Both are UDP-only protocols; a TCP connect attempt would only
            # ever time out, which is not the same thing as "unreachable".
            on_result(p.uid, None, SKIP_UDP)
            return
        result = metrics.tcp_connect_delay(p.address, p.port, attempts=1)
        avg = result["avg"]
        on_result(p.uid, avg, None if avg is not None else "unreachable")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, p) for p in profiles if not cancel.is_set()]
        for fut in as_completed(futures):
            fut.result()


class ResultStore:
    """Per-profile speed-test results, keyed by uid.

    Deliberately outside profiles/: ProfileStore.list() globs profiles/*.json
    and this dict-of-dicts shape would parse as a bogus profile there.

    on_result fires from worker threads (real_delay_all/tcping_all run in a
    thread pool), and the UI saves a result from each callback as it
    arrives, so every write goes through one lock and lands on disk with an
    atomic replace -- never a read/modify/write race or a torn file from two
    threads writing at once.
    """

    def __init__(self) -> None:
        self.file = paths.base_dir() / "profile_stats.json"
        self._lock = threading.Lock()

    def load(self) -> dict:
        if not self.file.exists():
            return {}
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_name(self.file.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.file)

    def get(self, uid: str) -> dict | None:
        with self._lock:
            return self.load().get(uid)

    def set(self, uid: str, **fields) -> None:
        with self._lock:
            data = self.load()
            entry = dict(data.get(uid, {}))
            entry.update(fields)
            data[uid] = entry
            self.save(data)

    def prune(self, valid_uids) -> None:
        with self._lock:
            valid = set(valid_uids)
            data = self.load()
            pruned = {uid: v for uid, v in data.items() if uid in valid}
            if pruned != data:
                self.save(pruned)
