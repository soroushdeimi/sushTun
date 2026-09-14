"""DnsPage (embeddable): malformed fields and config-check failures refuse
inline on the page's status label and never touch the stored dns config. The
dialog is the same page behind a thin wrapper, so that behaviour is covered
here once for both entry points.
"""
from __future__ import annotations

import copy
import os
import time

import pytest

if os.environ.get("CI"):
    import PySide6  # noqa: F401
else:
    pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from xrayui.core import xraycheck  # noqa: E402
from xrayui.core.settings import DEFAULTS  # noqa: E402
from xrayui.ui.dns_page import DnsPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _pump(condition, timeout=5.0) -> None:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


@pytest.mark.parametrize("entry,fragment", [
    ("8.8.8.8:5353", "scheme"),        # Xray parses a scheme-less entry as a URL
    ("localhost", "loop"),             # resolves back into this app's own resolver
    ("not a server", "spaces"),
    ("https://", "no server after the scheme"),
])
def test_invalid_server_refuses_inline(qapp, entry, fragment):
    page = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    page.servers.setPlainText(entry)
    original = copy.deepcopy(DEFAULTS["dns"])

    page.apply()

    assert fragment in page.status_label.text(), f"no refusal shown for {entry}"
    assert page.result_dns() == original


def test_config_check_failure_leaves_settings_unchanged(qapp, monkeypatch):
    # dns fields are valid here; the refusal comes from the real
    # render+validate round trip, which is stubbed to fail like xray would
    # on an unknown geosite category in the active routing.
    monkeypatch.setattr(xraycheck, "check_config",
                        lambda *a, **k: "unknown geosite category: not-a-real-category-xyz")
    bad_routing = copy.deepcopy(DEFAULTS["routing"])
    bad_routing["bypass_domains"] = ["geosite:not-a-real-category-xyz"]
    page = DnsPage(DEFAULTS["dns"], bad_routing)
    original = copy.deepcopy(DEFAULTS["dns"])
    page.servers.setPlainText("1.1.1.1")

    page.apply()
    _pump(lambda: not page._busy)

    assert "unknown geosite category" in page.status_label.text()
    assert page.result_dns() == original
