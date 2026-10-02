"""Prefix diagnostics must distinguish reachability from exit verification."""
import threading
from contextlib import contextmanager

import pytest

from xrayui.core import chain_test, chains, geo_exit, speedtest
from xrayui.core.profiles import Profile


@pytest.fixture
def plan():
    profiles = [Profile(uid=f'h{i}', name=f'Hop {i}', protocol='vless',
                        address='127.0.0.1', port=1234,
                        id='11111111-1111-1111-1111-111111111111') for i in range(3)]
    return chains.resolve(chains.Chain(uid='sample', hops=[p.uid for p in profiles]), profiles)


@pytest.mark.parametrize('delays,ips,verdict,broken', [
    ([40, 100, 90, 20], ['a', 'b', 'c', 'c'], 'OK', None),
    ([40, 100, 90, 20], ['a', 'b', 'a', 'c'], 'SKIPS_HOPS', None),
    ([None, None, None, 20], ['', '', '', 'c'], 'BROKEN_AT', 1),
    ([40, None, None, 20], ['a', '', '', 'c'], 'BROKEN_AT', 2),
    ([40, 100, 90, 20], ['a', 'b', 'd', 'c'], 'UNVERIFIED', None),
    ([40, 100, 90, 20], ['a', 'b', '', ''], 'UNVERIFIED', None),
])
def test_reports(monkeypatch, tmp_path, plan, delays, ips, verdict, broken):
    monkeypatch.setattr(chain_test.paths, 'base_dir', lambda: tmp_path)
    started, stopped, downloads = [], [], []

    @contextmanager
    def temporary(profiles, **kwargs):
        port = len(started)
        started.append([p.uid for p in profiles])
        try:
            yield port
        finally:
            stopped.append(port)

    monkeypatch.setattr(chain_test, '_temporary', temporary)
    monkeypatch.setattr(speedtest, '_measure_one', lambda port, *a: speedtest.Measured(
        delays[port], None if delays[port] is not None else 'timeout', 150))
    monkeypatch.setattr(geo_exit, 'detect', lambda proxy, timeout: geo_exit.ExitInfo(
        'de', ips[int(proxy.rsplit(':', 1)[1])]))
    monkeypatch.setattr(chain_test, '_download', lambda port, *a: downloads.append(port) or 12.5)
    report = chain_test.test_chain(plan, mode='warm', url='https://example.test',
                                   download_url='https://example.test/file', timeout=1,
                                   cancel=threading.Event(), on_progress=lambda *a: None)
    assert report.verdict == verdict
    assert report.broken_at == broken
    assert started == [['h0'], ['h0', 'h1'], ['h0', 'h1', 'h2'], ['h2']]
    assert stopped == [0, 1, 2, 3]
    assert downloads == ([2] if delays[2] is not None else [])
    if verdict == 'OK':
        assert [p.latency_ms for p in report.prefixes] == [40, 60, 0]
        assert report.download_mbps == 12.5
    saved = chain_test.ResultStore().get(plan.uid)
    assert saved['verdict'] == verdict
    assert saved['timestamp'] > 0


def test_cancel_stops_early(monkeypatch, tmp_path, plan):
    monkeypatch.setattr(chain_test.paths, 'base_dir', lambda: tmp_path)
    cancel = threading.Event()
    stopped = []

    @contextmanager
    def temporary(*a, **kw):
        try:
            yield 10
        finally:
            stopped.append(True)

    monkeypatch.setattr(chain_test, '_temporary', temporary)
    def measure(*a):
        cancel.set()
        return speedtest.Measured(10, None, 20)
    monkeypatch.setattr(speedtest, '_measure_one', measure)
    monkeypatch.setattr(geo_exit, 'detect', lambda *a: pytest.fail('detect after cancel'))
    report = chain_test.test_chain(plan, mode='warm', url='', download_url='', timeout=1,
                                   cancel=cancel, on_progress=lambda *a: None)
    assert report.verdict == 'CANCELLED'
    assert stopped == [True]
    assert chain_test.ResultStore().get(plan.uid) is None


def test_prefix_config_order(plan):
    cfg = chain_test.build_config(plan.profiles, 12345, '')
    assert cfg['outbounds'][0]['tag'] == 'proxy'
    assert cfg['outbounds'][0]['streamSettings']['sockopt']['dialerProxy'] == 'chain-2'
    one = chain_test.build_config(plan.profiles[:1], 12345, '')
    assert one['outbounds'][0]['tag'] == 'proxy'
    assert 'dialerProxy' not in one['outbounds'][0]['streamSettings']['sockopt']


def test_cold_mode_uses_warm_prefix_differences(monkeypatch, tmp_path, plan):
    monkeypatch.setattr(chain_test.paths, 'base_dir', lambda: tmp_path)
    ports = iter(range(4))
    calls = []

    @contextmanager
    def temporary(*a, **kw):
        yield next(ports)

    monkeypatch.setattr(chain_test, '_temporary', temporary)
    def measure(port, url, timeout, mode):
        calls.append(mode)
        value = [40, 75, 90, 20][port] if mode == 'warm' else 200
        return speedtest.Measured(value, None)
    monkeypatch.setattr(speedtest, '_measure_one', measure)
    monkeypatch.setattr(geo_exit, 'detect', lambda *a: geo_exit.ExitInfo('de', '1.2.3.4'))
    monkeypatch.setattr(chain_test, '_download', lambda *a: 10)
    report = chain_test.test_chain(plan, mode='cold', url='', download_url='', timeout=1,
                                   cancel=threading.Event(), on_progress=lambda *a: None,
                                   iface_alias='')
    assert calls == ['cold', 'warm'] * 4
    assert [p.latency_ms for p in report.prefixes] == [40, 35, 15]
    assert report.cold_ms == 200
    assert report.warm_ms == 90


@pytest.mark.parametrize('ready,raise_inside', [(False, False), (True, True), (True, False)])
def test_temporary_process_stopped(monkeypatch, plan, ready, raise_inside):
    class Process:
        stopped = False
        waited = False
        def poll(self):
            return None
        def terminate(self):
            self.stopped = True
        def wait(self, **kw):
            self.waited = True
    process = Process()
    monkeypatch.setattr(chain_test.subprocess, 'Popen', lambda *a, **kw: process)
    monkeypatch.setattr(speedtest, '_port_open', lambda *a: ready)
    try:
        with chain_test._temporary(plan.profiles, timeout=0, cancel=threading.Event(),
                                   iface_alias='', core_cfg={}):
            if raise_inside:
                raise RuntimeError('probe failed')
    except (OSError, RuntimeError):
        pass
    assert process.stopped
    assert process.waited


def test_download_uses_proxy_and_counts_bytes(monkeypatch):
    connections = []
    class Response:
        status = 200
        chunks = iter([b'a' * 1000, b'b' * 1000, b''])
        def read1(self, size):
            return next(self.chunks)
    class Connection:
        closed = False
        def __init__(self, host, port, **kw):
            assert (host, port) == ('127.0.0.1', 1234)
            connections.append(self)
        def request(self, method, url):
            assert url == 'http://example.test/file'
        def getresponse(self):
            return Response()
        def close(self):
            self.closed = True
    clock = iter([0, 1, 2, 3, 4])
    monkeypatch.setattr(chain_test.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(chain_test.http.client, 'HTTPConnection', Connection)
    assert chain_test._download(1234, 'http://example.test/file', 1, threading.Event()) == 0.004
    assert connections[0].closed
