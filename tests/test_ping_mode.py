"""Delay-test mode: warm (two requests, one connection) versus cold."""
from __future__ import annotations

import copy
import http.server
import threading
import time

import pytest

from xrayui.core import geo_exit, speedtest
from xrayui.core import settings as app_settings
from xrayui.core.profiles import Profile


class _Proxy(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, first_delay: float = 0.0, status: int = 204) -> None:
        self.connections = 0
        self.requests: list[str] = []
        self.first_delay = first_delay
        self.status = status
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                outer.connections += 1

            def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's own naming
                outer.requests.append(self.path)
                if len(outer.requests) == 1 and outer.first_delay:
                    time.sleep(outer.first_delay)
                self.send_response(outer.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        super().__init__(("127.0.0.1", 0), Handler)
        self.port = self.server_address[1]
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.shutdown()
        self.server_close()


@pytest.fixture
def proxy():
    made = []

    def make(**kw):
        made.append(_Proxy(**kw))
        return made[-1]

    yield make
    for p in made:
        p.close()


def test_warm_reports_the_smaller_of_two_requests_on_one_connection(proxy):
    srv = proxy(first_delay=0.25)
    m = speedtest._measure_one(srv.port, "http://example.invalid/", 5.0, "warm")
    delay, error = m

    assert error is None
    assert m.cold >= 250
    assert delay < m.cold
    assert srv.requests == ["http://example.invalid/"] * 2
    assert srv.connections == 1
    assert len(srv.requests) == 2


def test_cold_mode_sends_a_single_request(proxy):
    srv = proxy()
    m = speedtest._measure_one(srv.port, "http://example.invalid/", 5.0, "cold")

    assert m[1] is None and m[0] is not None
    assert m.cold is None
    assert len(srv.requests) == 1


def test_default_mode_is_warm(proxy):
    srv = proxy()
    speedtest._measure_one(srv.port, "http://example.invalid/", 5.0)
    assert len(srv.requests) == 2


@pytest.mark.parametrize("mode", ["warm", "cold"])
def test_status_handling_is_the_same_in_both_modes(proxy, mode):
    for status, expected in ((503, "connection failed"), (404, "HTTP 404")):
        srv = proxy(status=status)
        delay, error = speedtest._measure_one(srv.port, "http://example.invalid/", 5.0, mode)
        assert delay is None
        assert error == expected

    srv = proxy(status=200)
    delay, error = speedtest._measure_one(srv.port, "http://example.invalid/", 5.0, mode)
    assert error is None and delay is not None


@pytest.mark.parametrize("mode", ["warm", "cold"])
def test_unreachable_proxy_is_an_error_not_an_exception(mode):
    delay, error = speedtest._measure_one(1, "http://example.invalid/", 1.0, mode)
    assert delay is None and error


def test_old_settings_without_a_mode_get_warm():
    assert app_settings.DEFAULTS["speedtest"]["mode"] == "warm"
    merged = app_settings._merge(copy.deepcopy(app_settings.DEFAULTS),
                                 {"speedtest": {"url": "http://x/", "timeout_s": 3}})
    assert merged["speedtest"]["mode"] == "warm"
    assert merged["speedtest"]["url"] == "http://x/"


# -- exit detection during a test -------------------------------------------
P = Profile(name="p", protocol="vless", address="a.example.com", port=443, id="u", uid="u1")


def _run_group(monkeypatch, measured, info):
    monkeypatch.setattr(speedtest, "_measure_one", lambda *a, **k: measured)
    monkeypatch.setattr(geo_exit, "detect", lambda *a, **k: info)
    results, details = [], []
    speedtest._measure_group(
        [P], [1234], url="http://x/", timeout=1,
        on_result=lambda *a: results.append(a), cancel=threading.Event(),
        mode="warm", on_detail=lambda uid, f: details.append((uid, f)))
    return results, details


def test_a_successful_measurement_reports_cold_value_country_and_exit_ip(monkeypatch):
    results, details = _run_group(
        monkeypatch, speedtest.Measured(12.0, None, 30.0), geo_exit.ExitInfo("de", "1.2.3.4"))

    assert results == [("u1", 12.0, None)]
    assert details == [("u1", {"cold_ms": 30.0, "country": "de", "exit_ip": "1.2.3.4"})]


def test_a_failed_detection_reports_no_country(monkeypatch):
    _, details = _run_group(monkeypatch, speedtest.Measured(12.0, None, 30.0), None)
    assert details == [("u1", {"cold_ms": 30.0})]


def test_a_failed_measurement_skips_detection(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no detection for a failed profile")

    monkeypatch.setattr(geo_exit, "detect", boom)
    monkeypatch.setattr(speedtest, "_measure_one", lambda *a, **k: speedtest.Measured(None, "x"))
    details = []
    speedtest._measure_group(
        [P], [1234], url="http://x/", timeout=1, on_result=lambda *a: None,
        cancel=threading.Event(), on_detail=lambda uid, f: details.append(f))
    assert details == []


def test_cold_probe_never_bypasses_explicit_proxy(proxy, monkeypatch):
    monkeypatch.setenv('no_proxy', '*')
    srv = proxy()
    measured = speedtest._measure_one(srv.port, 'http://example.invalid/', 1, 'cold')
    assert measured[1] is None
    assert srv.requests == ['http://example.invalid/']
