"""Stranded DNS, field-overridable template, and the log-level toggle.

State records one adapter alias, so a session that died while a *different*
adapter was active left that adapter pinned to 127.0.0.1 forever: nothing
listens there once xray exits, and Windows reports no internet on it.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from xrayui import paths
from xrayui.core import connection, network, render
from xrayui.core import settings as app_settings
from xrayui.core.importer import parse_vless
from xrayui.core.network import DnsState, Interface
from xrayui.core.state import State

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"
SAMPLE = "vless://u@1.2.3.4:443?type=tcp&security=none#x"
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows DNS backend")


# -- the sweep -------------------------------------------------------------
@WINDOWS_ONLY
def test_stranded_adapters_exclude_the_one_being_restored(monkeypatch):
    monkeypatch.setattr(network.proc, "ps_lines",
                        lambda *a, **k: ["Wi-Fi", "Ethernet 3", ""])
    assert network.stranded_loopback_adapters(exclude="Ethernet 3") == ["Wi-Fi"]
    assert network.stranded_loopback_adapters() == ["Wi-Fi", "Ethernet 3"]


@WINDOWS_ONLY
def test_release_stranded_resets_to_dhcp_and_flushes(monkeypatch):
    ran = []
    monkeypatch.setattr(network.proc, "ps_lines", lambda *a, **k: ["Wi-Fi"])
    monkeypatch.setattr(network.proc, "run",
                        lambda args, **k: ran.append(list(args))
                        or types.SimpleNamespace(returncode=0, stdout=""))

    assert network.release_stranded_dns(exclude="Ethernet 3") == ["Wi-Fi"]
    assert ["netsh", "interface", "ipv4", "set", "dnsservers",
            "name=Wi-Fi", "dhcp"] in ran
    assert ["ipconfig", "/flushdns"] in ran


@WINDOWS_ONLY
def test_release_stranded_reports_only_adapters_that_actually_reset(monkeypatch):
    monkeypatch.setattr(network.proc, "ps_lines", lambda *a, **k: ["Wi-Fi"])
    monkeypatch.setattr(network.proc, "run",
                        lambda args, **k: types.SimpleNamespace(returncode=1, stdout=""))
    assert network.release_stranded_dns() == []


@WINDOWS_ONLY
def test_nothing_stranded_means_no_flush(monkeypatch):
    ran = []
    monkeypatch.setattr(network.proc, "ps_lines", lambda *a, **k: [])
    monkeypatch.setattr(network.proc, "run",
                        lambda args, **k: ran.append(list(args))
                        or types.SimpleNamespace(returncode=0, stdout=""))
    assert network.release_stranded_dns() == []
    assert ran == []


def test_restore_sweeps_other_adapters_and_reports_them(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "runtime_config", lambda: tmp_path / "config.runtime.json")
    State().save(Interface("Ethernet 3", "172.21.1.24", "172.21.1.1", 28),
                 "185.229.204.23", 25, DnsState(mode="DHCP", servers=[]))

    seen = {}
    monkeypatch.setattr(connection.network, "remove_routes", lambda ip=None: None)
    monkeypatch.setattr(connection.network, "restore_dns", lambda *a, **k: True)
    monkeypatch.setattr(connection.bootrestore, "uninstall", lambda: None)
    def fake_release(exclude=None):
        seen["exclude"] = exclude
        return ["Wi-Fi"]

    monkeypatch.setattr(connection.network, "release_stranded_dns", fake_release)

    steps = []
    conn = connection.Connection(on_step=steps.append)
    conn.xray.stop = lambda: None
    conn.tun2socks.stop = lambda: None
    conn._restore()

    # The adapter we just restored from backup must not be reset to DHCP.
    assert seen["exclude"] == "Ethernet 3"
    assert any("Wi-Fi" in s for s in steps)


# -- field-overridable template -------------------------------------------
def test_template_next_to_the_exe_wins_over_the_bundled_one(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    external = tmp_path / "external"
    bundled.mkdir()
    external.mkdir()
    (bundled / "config.template.json").write_text("bundled", encoding="utf-8")
    (external / "config.template.json").write_text("external", encoding="utf-8")

    monkeypatch.setattr(paths, "resource_dir", lambda: bundled)
    monkeypatch.setattr(paths, "base_dir", lambda: external)
    assert paths.config_template().read_text(encoding="utf-8") == "external"

    (external / "config.template.json").unlink()
    assert paths.config_template().read_text(encoding="utf-8") == "bundled"


# -- log level -------------------------------------------------------------
def test_log_level_overrides_the_template():
    out = json.loads(render.build_text(parse_vless(SAMPLE), "Wi-Fi", TEMPLATE,
                                       log_level="debug"))
    assert out["log"]["loglevel"] == "debug"


def test_log_level_defaults_to_the_template_value():
    out = json.loads(render.build_text(parse_vless(SAMPLE), "Wi-Fi", TEMPLATE))
    assert out["log"]["loglevel"] == "warning"


def test_bogus_log_level_is_ignored_rather_than_written_through():
    out = json.loads(render.build_text(parse_vless(SAMPLE), "Wi-Fi", TEMPLATE,
                                       log_level="chatty"))
    assert out["log"]["loglevel"] == "warning"


def test_log_level_is_a_known_setting_with_a_safe_default():
    assert app_settings.DEFAULTS["log_level"] == "warning"
    assert "debug" in app_settings.LOG_LEVELS
    loaded = app_settings.load()
    assert loaded["log_level"] in app_settings.LOG_LEVELS
