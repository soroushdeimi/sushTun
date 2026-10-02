"""Isolated prefix probes and exit verification for ordered proxy chains."""
from __future__ import annotations

import http.client
import json
import subprocess
import tempfile
import threading
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

from .. import paths
from . import chains, geo_exit, network, outbounds, proc, settings, speedtest

DEFAULT_DOWNLOAD_URL = 'https://speed.cloudflare.com/__down?bytes=25000000'
__test__ = False


@dataclass
class PrefixResult:
    delay_ms: float | None = None
    warm_ms: float | None = None
    cold_ms: float | None = None
    latency_ms: float | None = None
    country: str = ''
    exit_ip: str = ''
    error: str | None = None


@dataclass
class ChainReport:
    uid: str
    verdict: str = 'UNVERIFIED'
    broken_at: int | None = None
    prefixes: list[PrefixResult] = field(default_factory=list)
    last_hop: PrefixResult | None = None
    country: str = ''
    exit_ip: str = ''
    delay_ms: float | None = None
    warm_ms: float | None = None
    cold_ms: float | None = None
    download_mbps: float | None = None
    timestamp: float = field(default_factory=time.time)


class ResultStore(speedtest.ResultStore):
    def __init__(self):
        super().__init__()
        self.file = paths.base_dir() / 'chain_stats.json'


def build_config(profiles, port, iface_alias, core_cfg=None):
    cfg = {'log': {'loglevel': 'warning'},
           'inbounds': [{'listen': '127.0.0.1', 'port': port,
                         'protocol': 'http', 'settings': {}}],
           'outbounds': [outbounds.build(profiles[-1], 'proxy')]}
    if len(profiles) > 1:
        plan = chains.resolve(chains.Chain(hops=[p.uid for p in profiles]), profiles)
        chains.apply(cfg, plan, core_cfg)
    else:
        from . import coreopts
        coreopts.apply_all(cfg, core_cfg or {}, profiles[0])
    return json.loads(json.dumps(cfg).replace('__INTERFACE__', iface_alias)
                      .replace('__IFACE__', iface_alias))


@contextmanager
def _temporary(profiles, *, timeout, cancel, iface_alias, core_cfg):
    port = speedtest._free_port()
    with tempfile.TemporaryDirectory(prefix='chain-test-') as directory:
        from pathlib import Path
        config = Path(directory) / 'config.json'
        config.write_text(json.dumps(build_config(profiles, port, iface_alias, core_cfg)))
        with (Path(directory) / 'xray.log').open('w') as log:
            process = subprocess.Popen(
                [str(paths.xray_exe()), 'run', '-c', str(config)], stdout=log,
                stderr=subprocess.STDOUT, cwd=directory,
                env=proc.child_env({'XRAY_LOCATION_ASSET': str(paths.asset_dir())}),
                creationflags=proc.CREATE_NO_WINDOW, startupinfo=proc._startupinfo())
            finished = threading.Event()

            def watch_cancel():
                while not finished.wait(0.05):
                    if cancel.is_set():
                        if process.poll() is None:
                            process.terminate()
                        return

            watcher = threading.Thread(target=watch_cancel, daemon=True)
            watcher.start()
            try:
                deadline = time.monotonic() + timeout
                while not speedtest._port_open(port):
                    if cancel.is_set() or process.poll() is not None or time.monotonic() > deadline:
                        raise OSError('test proxy did not become ready')
                    cancel.wait(0.05)
                yield port
            finally:
                finished.set()
                watcher.join()
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def _download(port, url, timeout, cancel):
    parts = urllib.parse.urlsplit(url)
    secure = parts.scheme == 'https'
    cls = http.client.HTTPSConnection if secure else http.client.HTTPConnection
    conn = cls('127.0.0.1', port, timeout=min(timeout, 1.0))
    target = url
    if secure:
        conn.set_tunnel(parts.hostname, parts.port or 443)
        target = urllib.parse.urlunsplit(('', '', parts.path or '/', parts.query, ''))
    started = time.monotonic()
    count = 0
    try:
        conn.request('GET', target)
        response = conn.getresponse()
        if not 200 <= response.status < 300:
            return None
        while not cancel.is_set() and time.monotonic() - started < 8:
            data = response.read1(65536)
            if not data:
                break
            count += len(data)
        return count * 8 / max(time.monotonic() - started, 0.001) / 1e6
    except (OSError, http.client.HTTPException):
        return None
    finally:
        conn.close()


def test_chain(plan, *, mode, url, download_url=DEFAULT_DOWNLOAD_URL, timeout=10,
               cancel, on_progress, iface_alias=None):
    if cancel.is_set():
        return ChainReport(plan.uid, verdict='CANCELLED')
    cfg = settings.load().get('core', {})
    chains.check(plan, cfg)
    if mode not in speedtest.MODES:
        raise ValueError('invalid delay mode')
    report = ChainReport(plan.uid)
    if iface_alias is None:
        iface = network.detect_interface()
        iface_alias = iface.alias if iface else ''
    profiles = plan.profiles

    def probe(items, full=False):
        result = PrefixResult()
        if cancel.is_set():
            return result
        try:
            with _temporary(items, timeout=timeout, cancel=cancel,
                            iface_alias=iface_alias, core_cfg=cfg) as port:
                if cancel.is_set():
                    return result
                measured = speedtest._measure_one(port, url, timeout, mode)
                result.delay_ms, result.error = measured
                result.cold_ms = measured.cold if mode == 'warm' else measured[0]
                if cancel.is_set() or result.delay_ms is None:
                    return result
                warm = (measured if mode == 'warm' else
                        speedtest._measure_one(port, url, timeout, 'warm'))
                result.warm_ms = warm[0]
                if cancel.is_set():
                    return result
                info = geo_exit.detect(f'http://127.0.0.1:{port}', timeout)
                if info:
                    result.country, result.exit_ip = info.country, info.ip
                if full and not cancel.is_set():
                    report.download_mbps = _download(port, download_url, timeout, cancel)
        except OSError as exc:
            result.error = str(exc)
        return result

    for index in range(1, len(profiles) + 1):
        if cancel.is_set():
            break
        on_progress(index, len(profiles) + 1)
        result = probe(profiles[:index], index == len(profiles))
        previous = report.prefixes[-1].warm_ms if report.prefixes else 0
        if result.warm_ms is not None and previous is not None:
            result.latency_ms = max(0, result.warm_ms - previous)
        report.prefixes.append(result)
    if not cancel.is_set():
        on_progress(len(profiles) + 1, len(profiles) + 1)
        report.last_hop = probe(profiles[-1:])
    if cancel.is_set():
        report.verdict = 'CANCELLED'
        return report
    full = report.prefixes[-1]
    report.country, report.exit_ip = full.country, full.exit_ip
    report.delay_ms, report.cold_ms = full.delay_ms, full.cold_ms
    report.warm_ms = full.warm_ms
    if full.delay_ms is None:
        report.verdict = 'BROKEN_AT'
        report.broken_at = next(i for i, result in enumerate(report.prefixes, 1)
                                if result.delay_ms is None)
    elif full.exit_ip and report.last_hop.exit_ip:
        if full.exit_ip == report.last_hop.exit_ip:
            report.verdict = 'OK'
        elif any(p.exit_ip == full.exit_ip for p in report.prefixes[:-1]):
            report.verdict = 'SKIPS_HOPS'
    data = asdict(report)
    data.pop('uid')
    ResultStore().set(plan.uid, **data)
    return report
