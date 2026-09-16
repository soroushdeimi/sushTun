"""Unit tests for the tour's UX check helpers -- mainly the fa bidi scanner:
an LTR-isolated run must not be flagged even when the isolate wraps a larger
run or sits flush against the PDI, while a bare digit+unit run in an RTL
widget must be (the false positive / false negative pair this guards against).
"""
from __future__ import annotations

import os

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from tools.ui_tour import Tour, _unscoped_bidi_runs  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def tour(tmp_path) -> Tour:
    app = QApplication.instance() or QApplication([])
    return Tour(app, tmp_path, "fa", "820x560")


def test_bidi_check_isolated_text_has_no_findings(qapp, tour):
    # A run flush against the closer ("650 ms" right before the PDI) and a run
    # inside a larger isolate must both pass, plus RLI/FSI variants.
    for text in ("\u2066650 ms\u2069",
                 "\u2067\u2066650 ms\u2069\u2069",
                 "\u2066650 ms · 85 ms · 45 ms\u2069"):
        assert _unscoped_bidi_runs(text) == [], text


def _rtl_label(text: str) -> QWidget:
    host = QWidget()
    label = QLabel(text)
    label.setLayoutDirection(Qt.RightToLeft)
    label.setParent(host)
    label.show()
    return host


def test_bidi_check_bare_run_in_rtl_widget_is_found(qapp, tour):
    host = _rtl_label("650 ms")
    host.show()
    qapp.processEvents()
    try:
        tour.state_begin()
        tour._check_bidi(host, "rtl_widget")
    finally:
        host.close()
    assert any(f[1] == "bidi" for f in tour.findings), tour.findings


def test_bidi_check_isolated_label_in_rtl_widget_is_clean(qapp, tour):
    host = _rtl_label("\u2066650 ms\u2069")
    host.show()
    qapp.processEvents()
    try:
        tour.state_begin()
        tour._check_bidi(host, "rtl_widget")
    finally:
        host.close()
    assert tour.findings == [], tour.findings
