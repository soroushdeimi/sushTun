"""Security notifications: a tray message once per incident (and again after
recovery), the periodic leak check that never runs when disabled, and the
first-run tour's security step.

The red status line (kill switch) is the existing subtitle and is not tested
here; these cover the OS notification and the leak-check wiring that ride the
status/route ticks.
"""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui import paths  # noqa: E402
from xrayui.core import leakcheck as leakcheck_mod  # noqa: E402
from xrayui.i18n import set_language, tr  # noqa: E402
from xrayui.ui import main_window as mw  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _english():
    set_language("en")
    yield
    set_language("en")


@pytest.fixture
def win(qapp, tmp_path, monkeypatch, flush_widgets):
    monkeypatch.setattr(paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "profiles_dir", lambda: tmp_path / "profiles")
    paths.ensure_dirs()
    flush_widgets()
    window = mw.MainWindow(elevated=True)
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def _connected(win, monkeypatch):
    monkeypatch.setattr(win.conn, "is_connected", lambda: True)


def _notify_recorder(win, monkeypatch):
    calls: list[tuple[str, str, object]] = []
    monkeypatch.setattr(win, "_notify",
                        lambda title, message, icon: calls.append(
                            (title, message, icon)))
    return calls


def test_tunnel_drop_notifies_once_and_again_after_recovery(win, monkeypatch):
    calls = _notify_recorder(win, monkeypatch)
    _connected(win, monkeypatch)
    win._xray_running = False  # connected but the tunnel process is gone
    win._check_security_alerts()
    assert len(calls) == 1
    assert "VPN dropped" in calls[0][1]
    # The same incident, still active: no repeat.
    win._check_security_alerts()
    assert len(calls) == 1
    # The tunnel comes back: the incident clears, no notification.
    win._xray_running = True
    win._check_security_alerts()
    assert len(calls) == 1
    # It drops again: a new incident, so it notifies once more.
    win._xray_running = False
    win._check_security_alerts()
    assert len(calls) == 2


def test_leak_finding_notifies_once_per_incident(win, monkeypatch):
    calls = _notify_recorder(win, monkeypatch)
    _connected(win, monkeypatch)
    win._xray_running = True
    win._leak_verdict = leakcheck_mod.Verdict(leakcheck_mod.IP_MATCHES_REAL)
    win._check_security_alerts()
    assert len(calls) == 1
    assert "real IP" in calls[0][1]
    # Same finding on the next tick: quiet.
    win._check_security_alerts()
    assert len(calls) == 1
    # The check passes: the incident clears.
    win._leak_verdict = leakcheck_mod.Verdict(leakcheck_mod.OK)
    win._check_security_alerts()
    assert len(calls) == 1
    # It leaks again: a fresh incident notifies.
    win._leak_verdict = leakcheck_mod.Verdict(leakcheck_mod.IP_MATCHES_REAL)
    win._check_security_alerts()
    assert len(calls) == 2


def test_leak_finding_honours_notify_off(win, monkeypatch):
    calls = _notify_recorder(win, monkeypatch)
    _connected(win, monkeypatch)
    win._xray_running = True
    win.settings["leakcheck"]["notify"] = False
    win._leak_verdict = leakcheck_mod.Verdict(leakcheck_mod.IP_MATCHES_REAL)
    win._check_security_alerts()
    # A leak finding is suppressed when the user turned notifications off.
    assert calls == []


def test_tunnel_drop_notifies_even_when_leak_notify_is_off(win, monkeypatch):
    calls = _notify_recorder(win, monkeypatch)
    _connected(win, monkeypatch)
    win._xray_running = False
    win.settings["leakcheck"]["notify"] = False
    win._check_security_alerts()
    # The tunnel drop is a safety alert, not a leak finding: it always notifies.
    assert len(calls) == 1
    assert "VPN dropped" in calls[0][1]


def test_no_notification_when_disconnected(win, monkeypatch):
    calls = _notify_recorder(win, monkeypatch)
    monkeypatch.setattr(win.conn, "is_connected", lambda: False)
    win._xray_running = False
    win._leak_verdict = leakcheck_mod.Verdict(leakcheck_mod.IP_MATCHES_REAL)
    win._check_security_alerts()
    assert calls == []


def test_leak_check_never_runs_when_disabled(win, monkeypatch):
    win.settings["leakcheck"]["enabled"] = False
    jobs: list = []
    monkeypatch.setattr(win, "_run_async", lambda work, done: jobs.append((work, done)))
    _connected(win, monkeypatch)
    win._maybe_run_leak_check()
    assert jobs == []


def test_leak_check_runs_when_enabled_and_connected(win, monkeypatch):
    win.settings["leakcheck"]["enabled"] = True
    jobs: list = []
    monkeypatch.setattr(win, "_run_async", lambda work, done: jobs.append((work, done)))
    _connected(win, monkeypatch)
    monkeypatch.setattr(win.conn, "state", type("S", (), {"alias": "en0"})())
    # The probes are faked: a real run_check would hit the network.
    calls: list = []
    monkeypatch.setattr(leakcheck_mod, "run_check",
                        lambda *a, **k: calls.append("check")
                        or leakcheck_mod.Verdict(leakcheck_mod.OK))
    monkeypatch.setattr(leakcheck_mod, "run_dns_audit",
                        lambda: calls.append("dns") or leakcheck_mod.DnsAudit((), ()))
    monkeypatch.setattr(leakcheck_mod, "run_ipv6_audit",
                        lambda: calls.append("ipv6") or leakcheck_mod.Ipv6Audit((), ()))
    win._maybe_run_leak_check()
    assert len(jobs) == 1
    jobs[0][0]()  # run the work off-thread stand-in
    assert calls == ["check", "dns", "ipv6"]


def test_leak_check_does_not_run_when_disconnected(win, monkeypatch):
    win.settings["leakcheck"]["enabled"] = True
    jobs: list = []
    monkeypatch.setattr(win, "_run_async", lambda work, done: jobs.append((work, done)))
    monkeypatch.setattr(win.conn, "is_connected", lambda: False)
    win._maybe_run_leak_check()
    assert jobs == []


def test_leak_check_result_stores_the_verdict(win, monkeypatch):
    win.settings["leakcheck"]["enabled"] = True
    _connected(win, monkeypatch)
    monkeypatch.setattr(win.conn, "state", type("S", (), {"alias": "en0"})())
    verdict = leakcheck_mod.Verdict(leakcheck_mod.EXIT_IS_IRAN)
    dns = leakcheck_mod.DnsAudit((), ())
    ipv6 = leakcheck_mod.Ipv6Audit((), ())
    monkeypatch.setattr(leakcheck_mod, "run_check", lambda *a, **k: verdict)
    monkeypatch.setattr(leakcheck_mod, "run_dns_audit", lambda: dns)
    monkeypatch.setattr(leakcheck_mod, "run_ipv6_audit", lambda: ipv6)
    jobs: list = []
    monkeypatch.setattr(win, "_run_async", lambda work, done: jobs.append((work, done)))
    win._maybe_run_leak_check()
    work, done = jobs[0]
    done(result=work(), error=None)
    assert win._leak_verdict is verdict
    assert win._leak_dns_audit is dns
    assert win._leak_ipv6_audit is ipv6


def test_leak_check_failed_probe_keeps_last_verdict(win, monkeypatch):
    win.settings["leakcheck"]["enabled"] = True
    _connected(win, monkeypatch)
    monkeypatch.setattr(win.conn, "state", type("S", (), {"alias": "en0"})())
    win._leak_verdict = leakcheck_mod.Verdict(leakcheck_mod.OK)
    jobs: list = []
    monkeypatch.setattr(win, "_run_async", lambda work, done: jobs.append((work, done)))
    win._maybe_run_leak_check()
    work, done = jobs[0]
    done(result=None, error="probe failed")
    # A failed probe is not a leak: the last known verdict is kept.
    assert win._leak_verdict.status == leakcheck_mod.OK


def test_tour_has_a_security_step(win):
    steps = win._tour_steps()
    titles = [s.title for s in steps]
    assert tr("Protect your real IP") in titles
    step = next(s for s in steps if s.title == tr("Protect your real IP"))
    assert step.text
    # The recommended setup and the honest limits are both in the step.
    assert "kill switch" in step.text
    assert "strict mode" in step.text
    assert "leak check" in step.text
    assert "Serverless-only" in step.text
