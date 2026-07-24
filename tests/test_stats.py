import types

from xrayui.core import metrics


def _fake_run(stdout):
    return lambda *a, **k: types.SimpleNamespace(stdout=stdout, returncode=0)


def test_query_stats_sums_inbound(monkeypatch):
    payload = (
        '{"stat":['
        '{"name":"inbound>>>tun-in>>>traffic>>>uplink","value":100},'
        '{"name":"inbound>>>tun-in>>>traffic>>>downlink","value":900},'
        '{"name":"inbound>>>socks-in>>>traffic>>>uplink","value":10},'
        '{"name":"outbound>>>proxy>>>traffic>>>downlink","value":5}'
        ']}'
    )
    monkeypatch.setattr(metrics.proc, "run", _fake_run(payload))
    s = metrics.query_stats()
    assert s == {"up": 110, "down": 900}


def test_query_stats_bad_output(monkeypatch):
    monkeypatch.setattr(metrics.proc, "run", _fake_run("not json"))
    assert metrics.query_stats() is None
