import json
import socket
import subprocess
import threading

import pytest

from xrayui import paths
from xrayui.core import speedtest
from xrayui.core.profiles import Profile

VLESS_A = Profile(name="a", protocol="vless", address="a.example.com", port=443,
                   id="uuid-1", uid="u1")
VLESS_B = Profile(name="b", protocol="vless", address="b.example.com", port=443,
                   id="uuid-2", uid="u2")
WG = Profile(name="wg", protocol="wireguard", address="c.example.com", port=51820,
             id="SECRETKEY", pbk="PEERKEY", uid="uwg")


# -- build_test_config -------------------------------------------------------
def test_build_test_config_shape():
    profiles = [VLESS_A, WG]
    ports = [11000, 11001]
    cfg = speedtest.build_test_config(profiles, ports, "Wi-Fi")

    assert len(cfg["inbounds"]) == 2
    assert len(cfg["outbounds"]) == 2
    assert len(cfg["routing"]["rules"]) == 2
    assert cfg["log"]["loglevel"] == "warning"

    assert {i["tag"] for i in cfg["inbounds"]} == {f"in-{p.uid}" for p in profiles}
    assert {o["tag"] for o in cfg["outbounds"]} == {f"out-{p.uid}" for p in profiles}
    for rule in cfg["routing"]["rules"]:
        assert rule["inboundTag"][0].replace("in-", "out-") == rule["outboundTag"]

    for inbound in cfg["inbounds"]:
        assert inbound["protocol"] == "http"
        assert inbound["listen"] == "127.0.0.1"
    assert {i["port"] for i in cfg["inbounds"]} == set(ports)

    assert not any(i["tag"] == "tun-in" for i in cfg["inbounds"])
    assert not any(i.get("port") == 53 for i in cfg["inbounds"])
    assert not any(i["tag"] == "api" for i in cfg["inbounds"])
    assert "stats" not in cfg and "policy" not in cfg and "api" not in cfg

    text = json.dumps(cfg)
    assert "__IFACE__" not in text and "__INTERFACE__" not in text
    assert '"Wi-Fi"' in text


def test_build_test_config_is_pure():
    cfg1 = speedtest.build_test_config([VLESS_A], [1234], "eth0")
    cfg2 = speedtest.build_test_config([VLESS_A], [1234], "eth0")
    assert cfg1 == cfg2


# -- halving / cancel ---------------------------------------------------------
def test_halving_isolates_a_single_bad_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(speedtest.paths, "state_dir", lambda: tmp_path)
    (tmp_path / "speedtest.log").write_text(
        'Failed to start: main: failed to load config files: [/tmp/speedtest.json]'
        ' > infra/conf: failed to parse config: ... > empty "password"\n',
        encoding="utf-8",
    )

    good = [Profile(protocol="vless", address=f"h{i}.example.com", port=443, uid=f"u{i}")
            for i in range(4)]
    bad = Profile(protocol="vless", address="bad.example.com", port=443, uid="ubad")
    profiles = good[:2] + [bad] + good[2:]

    results: dict[str, tuple] = {}

    def on_result(uid, delay, error):
        results[uid] = (delay, error)

    def fake_run_batch(batch, ports, *, url, timeout, iface_alias, on_result, cancel, core_cfg=None):
        if any(p.uid == bad.uid for p in batch):
            return False
        for p in batch:
            on_result(p.uid, 42.0, None)
        return True

    speedtest.real_delay_all(
        profiles, on_result, threading.Event(), url="http://x", timeout=1,
        batch_size=50, iface_alias="Wi-Fi", run_batch=fake_run_batch,
    )

    for p in good:
        assert results[p.uid] == (42.0, None)
    assert results[bad.uid][0] is None
    assert results[bad.uid][1] == 'invalid config: empty "password"'


def test_whole_batch_succeeds_without_halving():
    profiles = [VLESS_A, VLESS_B]
    calls = []

    def fake_run_batch(batch, ports, *, url, timeout, iface_alias, on_result, cancel, core_cfg=None):
        calls.append([p.uid for p in batch])
        for p in batch:
            on_result(p.uid, 10.0, None)
        return True

    results = {}
    speedtest.real_delay_all(
        profiles, lambda uid, d, e: results.__setitem__(uid, (d, e)), threading.Event(),
        url="http://x", timeout=1, batch_size=50, iface_alias="Wi-Fi", run_batch=fake_run_batch,
    )

    assert calls == [["u1", "u2"]]  # never split: the batch succeeded whole
    assert results["u1"] == (10.0, None)
    assert results["u2"] == (10.0, None)


def test_cancel_stops_before_remaining_batches():
    profiles = [Profile(protocol="vless", address=f"h{i}.example.com", port=443, uid=f"u{i}")
                for i in range(4)]
    cancel = threading.Event()
    seen: list[str] = []

    def fake_run_batch(batch, ports, *, url, timeout, iface_alias, on_result, cancel, core_cfg=None):
        seen.extend(p.uid for p in batch)
        cancel.set()  # simulate a cancel firing during the first batch
        for p in batch:
            on_result(p.uid, 1.0, None)
        return True

    speedtest.real_delay_all(
        profiles, lambda *a: None, cancel, url="http://x", timeout=1,
        batch_size=2, iface_alias="Wi-Fi", run_batch=fake_run_batch,
    )

    assert seen == ["u0", "u1"]  # the second batch never ran


def test_is_skipped_only_recognizes_known_skip_reasons():
    assert speedtest.is_skipped(speedtest.SKIP_UDP)
    assert speedtest.is_skipped(speedtest.SKIP_UNAVAILABLE_WHILE_CONNECTED)
    assert not speedtest.is_skipped("unreachable")
    assert not speedtest.is_skipped("connection failed")
    assert not speedtest.is_skipped(None)


def test_wireguard_reported_unavailable_while_connected():
    results = {}
    speedtest.real_delay_all(
        [WG], lambda uid, d, e: results.__setitem__(uid, (d, e)), threading.Event(),
        url="http://x", timeout=1, iface_alias="Wi-Fi", connected=True,
        run_batch=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    assert results[WG.uid] == (None, speedtest.SKIP_UNAVAILABLE_WHILE_CONNECTED)
    assert speedtest.is_skipped(results[WG.uid][1])


# -- _measure_one --------------------------------------------------------
def test_measure_one_maps_http_503_to_connection_failed():
    import http.server

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's own naming
            self.send_response(503)
            self.end_headers()

        def log_message(self, *args):
            pass

    # Simulates Xray's HTTP inbound answering 503 itself because its
    # outbound couldn't connect -- the "server" here never even looks at
    # the requested URL.
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        delay, error = speedtest._measure_one(port, "http://example.invalid/", 2.0)
        assert delay is None
        assert error == "connection failed"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


# -- tcping --------------------------------------------------------------
def test_tcping_reports_open_and_closed_ports_and_skips_wireguard():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    open_port = srv.getsockname()[1]
    closed_port = speedtest._free_port()
    hy2 = Profile(protocol="hysteria2", address="d.example.com", port=443,
                  id="hy2-auth", uid="uhy2")
    try:
        profiles = [
            Profile(protocol="vless", address="127.0.0.1", port=open_port, uid="ok"),
            Profile(protocol="vless", address="127.0.0.1", port=closed_port, uid="closed"),
            WG,
            hy2,
        ]
        results = {}
        speedtest.tcping_all(
            profiles, lambda uid, d, e: results.__setitem__(uid, (d, e)), threading.Event()
        )
        assert results["ok"][0] is not None and results["ok"][1] is None
        assert not speedtest.is_skipped(results["ok"][1])
        assert results["closed"] == (None, "unreachable")
        assert not speedtest.is_skipped(results["closed"][1])
        assert results[WG.uid] == (None, speedtest.SKIP_UDP)
        assert speedtest.is_skipped(results[WG.uid][1])
        # Hysteria2 is UDP-only too -- a TCP connect attempt would only ever
        # time out, which isn't the same thing as "unreachable".
        assert results[hy2.uid] == (None, speedtest.SKIP_UDP)
        assert speedtest.is_skipped(results[hy2.uid][1])
    finally:
        srv.close()


# -- ResultStore --------------------------------------------------------
def test_result_store_round_trip_and_prune(tmp_path, monkeypatch):
    monkeypatch.setattr(speedtest.paths, "base_dir", lambda: tmp_path)
    store = speedtest.ResultStore()

    store.set("u1", delay_ms=12.3)
    store.set("u2", delay_ms=45.6)
    store.set("u1", tcping_ms=7.0)  # merges rather than overwriting

    assert store.get("u1") == {"delay_ms": 12.3, "tcping_ms": 7.0}
    assert store.get("u2") == {"delay_ms": 45.6}
    assert store.get("missing") is None

    store.prune(["u1"])
    assert store.get("u2") is None
    assert store.get("u1") == {"delay_ms": 12.3, "tcping_ms": 7.0}


def test_result_store_is_thread_safe_under_concurrent_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(speedtest.paths, "base_dir", lambda: tmp_path)
    store = speedtest.ResultStore()

    def worker(i: int) -> None:
        store.set(f"u{i}", delay_ms=float(i))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = store.load()
    assert len(data) == 20
    for i in range(20):
        assert data[f"u{i}"] == {"delay_ms": float(i)}


# -- Smoke: the generated config actually validates with the real binary ----
def test_generated_config_validates_with_real_xray(tmp_path):
    exe = paths.xray_exe()
    if not exe.exists():
        pytest.skip("bundled xray binary not present")

    profiles = [
        Profile(name="ws", protocol="vless", address="a.example.com", port=443,
                id="11111111-1111-1111-1111-111111111111",
                network="ws", security="tls", sni="a.example.com",
                path="/ws", host="a.example.com"),
        Profile(name="reality", protocol="vless", address="b.example.com", port=443,
                id="22222222-2222-2222-2222-222222222222",
                network="tcp", security="reality", sni="www.microsoft.com", fp="chrome",
                pbk="MjJyOOxAQ0m9MJp368E7lLKmXQz0GBBpuF12E-B6H1Q", sid="ab"),
        Profile(name="wg", protocol="wireguard", address="1.2.3.4", port=51820,
                id="cCWrsuGEXF6jGYh13IXrgA2lh7eJFRGX3h1VOZrNkmE=",
                pbk="bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
                wg_local_address="10.0.0.2/32"),
    ]
    ports = [speedtest._free_port() for _ in profiles]
    cfg = speedtest.build_test_config(profiles, ports, "eth0")
    cfg_path = tmp_path / "speedtest_smoke.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    result = subprocess.run(
        [str(exe), "run", "-test", "-c", str(cfg_path)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
