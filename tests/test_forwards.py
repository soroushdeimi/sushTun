"""Port forwarding: a local port that always reaches one fixed host:port."""
from __future__ import annotations

import copy
import json
import socket
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import connection, forwards, render, routing, settings, xraycheck
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden_main.json"

MAIN = Profile(uid="main", protocol="vless", address="m.example", port=443,
               id="11111111-1111-1111-1111-111111111111", network="tcp", security="tls",
               sni="m.example")
SSH = {"port": 2222, "target": "10.8.0.5:22", "via": "proxy", "network": "tcp"}
DNS = {"port": 5353, "target": "dns.example:53", "via": "direct", "network": "tcp,udp"}


def _core() -> dict:
    return copy.deepcopy(settings.DEFAULTS["core"])


@pytest.fixture(autouse=True)
def _port_free(monkeypatch):
    monkeypatch.setattr(forwards.exits, "port_is_free", lambda port: True)


def _render(forward_list) -> dict:
    r = settings.DEFAULTS["routing"]
    return json.loads(render.build_text(
        profile=MAIN, iface_alias="eth0", template_path=TEMPLATE,
        routing_rules=routing.build_rules(r), domain_strategy=routing.domain_strategy_for(r),
        stats=True, dns_cfg=settings.DEFAULTS["dns"], server_ip="203.0.113.7",
        core_cfg=_core(), forwards=forward_list))


# -- off means untouched ----------------------------------------------------------
def test_off_by_default():
    assert settings.DEFAULTS["forwards"] == []
    assert forwards.prepare(settings.DEFAULTS["forwards"], _core(), None) == ([], [])


def test_off_renders_main_branch_golden_configs_byte_for_byte():
    from tests.test_golden_main import _profiles, _variants
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["configs"]
    forward_list, warnings = forwards.prepare(settings.DEFAULTS["forwards"], _core(), None)
    assert warnings == []
    for pname, profile in _profiles().items():
        for vname, v in _variants().items():
            text = render.build_text(
                profile=profile, iface_alias="eth0", template_path=TEMPLATE,
                routing_rules=routing.build_rules(v["routing"]),
                domain_strategy=routing.domain_strategy_for(v["routing"]),
                stats=v["stats"], include_tun=v["include_tun"], log_level="warning",
                dns_cfg=v["dns"], tun_mtu=1420, server_ip="203.0.113.7", core_cfg=v["core"],
                forwards=forward_list)
            assert text == golden[f"{pname}/{vname}"], f"{pname}/{vname}"


# -- validation ------------------------------------------------------------------------
@pytest.mark.parametrize("target,ok", [
    ("10.8.0.5:22", True), ("dns.example:53", True), ("[2001:db8::1]:443", True),
    ("host", False), ("host:0", False), ("host:99999", False), ("a b:80", False),
    ("2001:db8::1:443", False), ("[nothost]:80", False), ("", False),
])
def test_targets_must_be_host_and_port(target, ok):
    assert (forwards.item_problem({**SSH, "target": target}, set()) is None) == ok


@pytest.mark.parametrize("over,reason", [
    ({"port": 80}, "between 1024 and 65535"),
    ({"port": 10808}, "already used by sushTun"),   # the local SOCKS port
    ({"port": 10085}, "already used by sushTun"),   # the stats API
    ({"via": "block"}, "through the tunnel or direct"),
    ({"network": "icmp"}, "TCP, UDP or both"),
])
def test_a_bad_forward_is_dropped_alone_with_a_warning(over, reason):
    kept, warnings = forwards.prepare([{**SSH, **over}, DNS], _core(), None)
    assert [f.port for f in kept] == [5353]
    assert len(warnings) == 1 and reason in warnings[0]


def test_the_multi_exit_port_is_taken_only_while_it_is_on():
    exits_on = {"enabled": True, "port": 2222}
    assert forwards.prepare([SSH], _core(), exits_on)[0] == []
    assert len(forwards.prepare([SSH], _core(), {**exits_on, "enabled": False})[0]) == 1


def test_two_forwards_on_one_port_keep_the_first():
    kept, warnings = forwards.prepare([SSH, {**DNS, "port": 2222}], _core(), None)
    assert [(f.port, f.host) for f in kept] == [(2222, "10.8.0.5")]
    assert "already used by sushTun" in warnings[0]


def test_a_busy_port_drops_only_that_forward(monkeypatch):
    monkeypatch.undo()  # the real bind test
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        if port < 1024:
            pytest.skip("the OS handed out a privileged port")
        kept, warnings = forwards.prepare([{**SSH, "port": port}], _core(), None)
    assert kept == []
    assert f"port {port} is in use" in warnings[0]


def test_connection_logs_each_dropped_forward(monkeypatch):
    steps: list[str] = []
    conn = connection.Connection(on_step=steps.append)
    kept = conn._forwards({"forwards": [{**SSH, "via": "x"}, DNS], "core": _core()})
    assert [f.port for f in kept] == [5353]
    assert steps == ["WARNING: Port forward skipped: choose through the tunnel or direct."]


# -- apply -------------------------------------------------------------------------------
def test_each_forward_is_a_local_dokodemo_inbound():
    kept, _ = forwards.prepare([SSH, DNS], _core(), None)
    out = _render(kept)
    ssh = next(i for i in out["inbounds"] if i["tag"] == "fwd-2222")
    assert ssh == {"tag": "fwd-2222", "listen": "127.0.0.1", "port": 2222,
                   "protocol": "dokodemo-door",
                   "settings": {"address": "10.8.0.5", "port": 22, "network": "tcp"}}
    dns = next(i for i in out["inbounds"] if i["tag"] == "fwd-5353")
    assert dns["settings"]["network"] == "tcp,udp"


def test_forward_rules_come_before_every_user_rule():
    kept, _ = forwards.prepare([SSH, DNS], _core(), None)
    rules = _render(kept)["routing"]["rules"]
    fwd = [i for i, r in enumerate(rules) if str(r.get("inboundTag", [""])[0]).startswith("fwd-")]
    first_user = next(i for i, r in enumerate(rules) if "inboundTag" not in r)
    assert fwd and max(fwd) < first_user  # so Iran-direct can't override "through the tunnel"
    assert rules[fwd[0]] == {"type": "field", "inboundTag": ["fwd-2222"], "outboundTag": "proxy"}
    assert rules[fwd[1]] == {"type": "field", "inboundTag": ["fwd-5353"], "outboundTag": "direct"}


def test_xray_test_accepts_the_forwards(tmp_path, monkeypatch):
    if not paths.xray_exe().exists():
        pytest.skip("bundled xray binary not present")
    monkeypatch.setattr(xraycheck.paths, "state_dir", lambda: tmp_path)
    kept, _ = forwards.prepare([SSH, DNS, {**SSH, "port": 8443, "target": "[2001:db8::1]:443"}],
                               _core(), None)
    text = render.build_text(profile=MAIN, iface_alias="lo", template_path=TEMPLATE,
                             include_tun=False, core_cfg=_core(), forwards=kept)
    assert '"tag": "fwd-2222"' in text and '"tag": "fwd-8443"' in text
    assert xraycheck.check_config(text) is None


# -- a port taken after the check must not take the tunnel down ------------------------
class _FakeXray:
    """Dies on the first start (port taken), runs on the second."""

    def __init__(self, deaths=1):
        self.starts: list = []
        self._deaths = deaths
        self._alive = False

    def start(self, cfg):
        self.starts.append(cfg)
        self._alive = len(self.starts) > self._deaths

    def is_running(self):
        return self._alive


def _conn_with(monkeypatch, tmp_path, xray, last_line):
    monkeypatch.setattr(connection, "_last_log_line", lambda: last_line)
    monkeypatch.setattr(connection.time, "sleep", lambda _s: None)
    conn = connection.Connection(on_step=lambda _m: None)
    conn.xray = xray
    return conn


def test_a_port_taken_after_the_check_starts_without_the_extras(monkeypatch, tmp_path):
    xray = _FakeXray()
    conn = _conn_with(monkeypatch, tmp_path, xray,
                      "failed to listen TCP on 2222 > bind: address already in use")
    built: list = []

    def build(exits, forwards):
        built.append((exits, forwards))
        return f"cfg-{len(built)}"

    kept, _ = forwards.prepare([SSH], _core(), None)
    conn._retry_without_extras(build, [], kept)
    assert built == [([], [])]          # rebuilt without the optional inbounds
    assert xray.starts == ["cfg-1"]     # and started again


def test_another_startup_failure_is_left_to_the_caller(monkeypatch, tmp_path):
    xray = _FakeXray()
    conn = _conn_with(monkeypatch, tmp_path, xray, "failed to parse config: bad json")
    kept, _ = forwards.prepare([SSH], _core(), None)
    conn._retry_without_extras(lambda e, f: "cfg", [], kept)
    assert xray.starts == []            # no second try: this is a real failure


def test_a_healthy_start_is_not_touched(monkeypatch, tmp_path):
    xray = _FakeXray(deaths=0)
    xray.start("cfg-0")
    conn = _conn_with(monkeypatch, tmp_path, xray, "")
    kept, _ = forwards.prepare([SSH], _core(), None)
    conn._retry_without_extras(lambda e, f: "cfg", [], kept)
    assert xray.starts == ["cfg-0"]


def test_a_switched_off_forward_is_skipped_without_a_warning():
    kept, warnings = forwards.prepare([{**SSH, "enabled": False}, DNS], _core(), None)
    assert [f.port for f in kept] == [5353] and warnings == []


def test_sharing_one_forward_does_not_share_the_others():
    kept, _ = forwards.prepare([SSH, {**DNS, "lan": True}], _core(), None)
    assert [(f.port, f.listen) for f in kept] == [(2222, "127.0.0.1"), (5353, "0.0.0.0")]
    out = _render(kept)
    listens = {i["tag"]: i["listen"] for i in out["inbounds"] if i["tag"].startswith("fwd-")}
    assert listens == {"fwd-2222": "127.0.0.1", "fwd-5353": "0.0.0.0"}

