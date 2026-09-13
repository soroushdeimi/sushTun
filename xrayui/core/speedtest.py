"""Real-delay and TCP-ping testing for a batch of profiles.

Runs its own throwaway Xray process against a config with one HTTP inbound
per profile, bound to the physical interface so testing works while the
tunnel is up. Never touches the live connection's process, config or log.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import paths
from . import metrics, outbounds, proc
from .profiles import Profile

OnResult = Callable[[str, "float | None", "str | None"], None]
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


def build_test_config(profiles: list[Profile], ports: list[int], iface_alias: str) -> dict:
    """A from-scratch Xray config: one HTTP inbound + outbound pair per profile.

    No tun inbound, no dns-in, no stats API -- this never touches the ports
    or tags the live connection owns, so it can run concurrently with it.
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
        outbounds_list.append(outbounds.build(p, out_tag))
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


def _measure_one(port: int, url: str, timeout: float) -> tuple[float | None, str | None]:
    proxy_url = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
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
        return None, str(e)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if status == 204 or 200 <= status < 300:
        return elapsed_ms, None
    if status == 503:
        # Xray's HTTP inbound answers 503 itself when its outbound couldn't
        # connect -- the target was never reached, so this isn't the
        # target's answer at all.
        return None, "connection failed"
    return None, f"HTTP {status}"


def _measure_group(
    profiles: list[Profile], ports: list[int], *,
    url: str, timeout: float, on_result: OnResult, cancel: threading.Event,
) -> None:
    with ThreadPoolExecutor(max_workers=max(1, len(profiles))) as pool:
        futures = {}
        for p, port in zip(profiles, ports, strict=True):
            if cancel.is_set():
                break
            futures[pool.submit(_measure_one, port, url, timeout)] = p
        for fut in as_completed(futures):
            p = futures[fut]
            delay, error = fut.result()
            on_result(p.uid, delay, error)


def _run_batch(
    profiles: list[Profile], ports: list[int], *,
    url: str, timeout: float, iface_alias: str, on_result: OnResult, cancel: threading.Event,
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

    cfg = build_test_config(profiles, ports, iface_alias)
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
                            on_result=on_result, cancel=cancel)
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
) -> None:
    if cancel.is_set() or not profiles:
        return
    ports = [_free_port() for _ in profiles]
    ok = run_batch(profiles, ports, url=url, timeout=timeout, iface_alias=iface_alias,
                    on_result=on_result, cancel=cancel)
    if ok:
        return
    if len(profiles) == 1:
        on_result(profiles[0].uid, None, f"invalid config: {_short_config_error()}")
        return
    mid = len(profiles) // 2
    _test_group(profiles[:mid], on_result, cancel,
                url=url, timeout=timeout, iface_alias=iface_alias, run_batch=run_batch)
    if cancel.is_set():
        return
    _test_group(profiles[mid:], on_result, cancel,
                url=url, timeout=timeout, iface_alias=iface_alias, run_batch=run_batch)


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
) -> None:
    run_batch = run_batch or _run_batch

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
                    url=url, timeout=timeout, iface_alias=iface_alias, run_batch=run_batch)


def tcping_all(
    profiles: list[Profile], on_result: OnResult, cancel: threading.Event, workers: int = 16,
) -> None:
    def one(p: Profile) -> None:
        if (p.protocol or "").lower() == "wireguard":
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
