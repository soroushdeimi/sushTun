"""UI smoke tests: the dialogs and the main window actually construct and round-trip.

Skipped when PySide6 is missing so a contributor without it still gets a green
suite -- except under CI, where a skip must fail instead. A silent skip reads
exactly like a pass in the run summary, and that is how the UI came to be the
one part of the app no test ever executed.
"""
from __future__ import annotations

import copy
import os

import pytest

if os.environ.get("CI"):
    # A skip here looks identical to a pass in the run summary, which is how
    # the UI went untested in the first place. In CI a missing or broken
    # PySide6 must fail loudly instead.
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

# Must be set before the first QApplication; there is no display on a CI runner.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import dns as dns_mod  # noqa: E402
from xrayui.core import settings as app_settings  # noqa: E402
from xrayui.ui.dialogs import SettingsDialog  # noqa: E402
from xrayui.ui.dns_dialog import DnsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def defaults():
    return copy.deepcopy(app_settings.DEFAULTS)


@pytest.fixture
def warnings(monkeypatch):
    """Capture QMessageBox.warning text instead of blocking on a modal."""
    seen: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: seen.append(a[2])), raising=False)
    return seen


# -- DNS dialog ------------------------------------------------------------
def test_dns_dialog_empty_round_trip_keeps_the_inherit_contract(qapp, defaults):
    out = DnsDialog(defaults["dns"]).result_dns()
    assert out["servers"] == []
    assert out["hosts"] == []
    assert out["query_strategy"] == ""
    # Empty must mean "inherit the template", never an empty server list.
    assert dns_mod.build_dns(out) == {}


def test_dns_dialog_preset_fills_and_round_trips(qapp, defaults, warnings):
    dlg = DnsDialog(defaults["dns"])
    dlg._fill(dns_mod.PRESETS["Quad9"])
    dlg.strategy.setCurrentIndex(dlg.strategy.findData("UseIPv4"))
    dlg.hosts.setPlainText("a.com = 1.2.3.4")
    dlg._save()

    assert not warnings
    out = dlg.result_dns()
    assert out["servers"] == dns_mod.PRESETS["Quad9"]
    assert out["query_strategy"] == "UseIPv4"
    # And the saved shape survives into the rendered Xray config.
    built = dns_mod.build_dns(out)
    assert built["servers"] == dns_mod.PRESETS["Quad9"]
    assert built["hosts"] == {"a.com": "1.2.3.4"}


def test_dns_dialog_reloads_what_it_saved(qapp, defaults):
    first = DnsDialog(defaults["dns"])
    first._fill(["1.1.1.1"])
    first.hosts.setPlainText("a.com = 1.2.3.4")
    first._save()
    saved = first.result_dns()

    second = DnsDialog(saved)
    assert second.servers.toPlainText().splitlines() == ["1.1.1.1"]
    assert second.hosts.toPlainText().splitlines() == ["a.com = 1.2.3.4"]


@pytest.mark.parametrize("entry,fragment", [
    ("8.8.8.8:5353", "scheme"),   # Xray parses a scheme-less entry as a URL
    ("localhost", "loop"),        # resolves back into this app's own resolver
    ("not a server", "spaces"),
    ("https://", "no server after the scheme"),
])
def test_dns_dialog_refuses_to_save_an_invalid_server(qapp, defaults, warnings, entry, fragment):
    dlg = DnsDialog(defaults["dns"])
    dlg.servers.setPlainText(entry)
    dlg._save()
    assert warnings, f"no warning for {entry}"
    assert fragment in warnings[-1]
    assert dlg.result() == 0, f"dialog accepted {entry}"


def test_dns_dialog_accepts_a_valid_server(qapp, defaults, warnings):
    dlg = DnsDialog(defaults["dns"])
    dlg.servers.setPlainText("https://1.1.1.1/dns-query")
    dlg._save()
    assert not warnings
    assert dlg.result() == 1


# -- Settings dialog -------------------------------------------------------
def test_settings_dialog_round_trips_the_new_knobs(qapp, defaults):
    dlg = SettingsDialog(defaults)
    assert dlg.values()["tun_mtu"] == 1420
    assert dlg.values()["log_level"] == "warning"

    dlg.tun_mtu.setValue(1280)
    dlg.log_level.setCurrentText("debug")
    values = dlg.values()
    assert values["tun_mtu"] == 1280
    assert values["log_level"] == "debug"
    assert values["ping_target"] == "1.1.1.1"


def test_settings_dialog_offers_every_known_log_level(qapp, defaults):
    dlg = SettingsDialog(defaults)
    shown = [dlg.log_level.itemText(i) for i in range(dlg.log_level.count())]
    assert shown == list(app_settings.LOG_LEVELS)


# -- Main window -----------------------------------------------------------
@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    from xrayui.ui.main_window import MainWindow
    win = MainWindow(elevated=False)
    yield win
    win.close()


def test_main_window_exposes_the_dns_and_baseline_entry_points(window):
    assert window.btn_dns.text().startswith("DNS")
    assert "Baseline" in [b.text() for b in window.tools._buttons]


def test_tool_signals_reach_their_handlers(window):
    fired = []
    window._run_tool = lambda fn: fired.append(fn.__name__)
    window.tools.baselineRequested.emit()
    window.tools.throughputRequested.emit()
    assert fired == ["_baseline_fn", "_throughput_fn"]


def test_baseline_reports_plainly_when_not_connected(window):
    assert "Not connected" in window._baseline_fn()
