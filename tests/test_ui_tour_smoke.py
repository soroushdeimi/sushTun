"""The tour must stay fast and side-effect free: a smoke test runs a tiny
slice and asserts the pieces a full run is built on, plus that nothing the
tour stubbed or styled leaks back out of this test into the rest of the
suite (the suite's other Qt tests run in the same process).
"""
from __future__ import annotations

import os
import time

import pytest

if os.environ.get("CI"):
    # Same contract as tests/test_ui.py: a skip under CI must be a loud
    # failure, not a silent green checkmark.
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from tools.ui_tour import TOUR_STATES, run_tour  # noqa: E402
from xrayui import i18n, paths  # noqa: E402
from xrayui.core import (  # noqa: E402
    connection as connection_mod,
)
from xrayui.core import (
    hotspot,
    metrics,
    network,
    xraycheck,
)
from xrayui.ui import main_window  # noqa: E402


def _snap(mod, attrs: list[str]) -> dict[str, object]:
    return {a: getattr(mod, a) for a in attrs if hasattr(mod, a)}


def _restore(mod, snap: dict[str, object]) -> None:
    for name, value in snap.items():
        setattr(mod, name, value)


def test_ui_tour_smoke_runs_fast_and_restores_global_state(tmp_path):
    _QMB = ["warning", "critical", "information", "question"]
    _METRICS = ["ping", "tcp_connect_delay", "throughput_sample", "query_stats",
                "baseline_sample", "diagnostics"]
    snap = {
        "connection": _snap(connection_mod, ["Connection"]),
        "main_window": _snap(main_window, ["Connection", "is_xray_running"]),
        "network": _snap(network, ["detect_interface"]),
        "hotspot": _snap(hotspot, ["supported"]),
        "xraycheck": _snap(xraycheck, ["check_config", "check_rules"]),
        "metrics": _snap(metrics, _METRICS),
        "qmb": _snap(QMessageBox, _QMB),
        "paths": _snap(paths, ["base_dir", "state_dir", "profiles_dir"]),
    }
    app = QApplication.instance() or QApplication([])
    old_layout = app.layoutDirection()
    old_ss = app.styleSheet()
    old_lang = i18n.current()

    try:
        selected = [s for s in TOUR_STATES
                    if s.name in {"main_disconnected", "tray_servers_submenu", "dns_dialog"}]
        started = time.monotonic()
        findings = run_tour(tmp_path / "tour", states=selected,
                            langs=["en"], sizes=[("1040x700", 1040, 700)])
        elapsed = time.monotonic() - started
    finally:
        for mod_name, mod in (("connection", connection_mod), ("main_window", main_window),
                              ("network", network), ("hotspot", hotspot),
                              ("xraycheck", xraycheck), ("metrics", metrics)):
            _restore(mod, snap[mod_name])
        _restore(QMessageBox, snap["qmb"])
        _restore(paths, snap["paths"])
        i18n.set_language(old_lang)
        app.setLayoutDirection(old_layout)
        app.setStyleSheet(old_ss)
        app.processEvents()

    out_dir = tmp_path / "tour" / "en" / "1040x700"
    assert (out_dir / "01_main_disconnected.png").exists()
    assert (out_dir / "02_tray_servers_submenu.png").exists()
    assert (out_dir / "03_dns_dialog.png").exists()

    index = (tmp_path / "tour" / "index.txt").read_text(encoding="utf-8")
    assert "requested width 1040, requested height 700" in index
    assert "actual " in index

    findings_txt = (tmp_path / "tour" / "findings.txt").read_text(encoding="utf-8")
    # These three states now fit the size they ask for. A size finding here
    # means a window started refusing to shrink again -- the very thing the
    # sidebar redesign fixed.
    assert not [line for line in findings_txt.splitlines() if "] size:" in line]
    for header in ("# Findings", "# Deduplicated summary",
                   "# Screenshots that need a human look"):
        assert header in findings_txt
    assert isinstance(findings, list)

    # The suite's other Qt tests run in this same process; the tour must not
    # have left Persian layout, Persian translations or test stubs behind.
    assert app.layoutDirection() == old_layout
    assert app.styleSheet() == old_ss
    assert i18n.current() == old_lang

    # A prompt for a human must stay prompt: 3 states, one language, one
    # size. The budget is generous because this runs on shared CI machines,
    # where a loaded box turned a 1s tour into 16s and failed the suite;
    # it still catches a tour that has become truly un-runnable.
    assert elapsed < 90.0, f"smoke tour took {elapsed:.1f}s"
