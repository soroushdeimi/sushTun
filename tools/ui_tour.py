"""A scripted tour of the real sushTun UI, offscreen, in en and fa, at two
window sizes -- for a human to eyeball and for automated UX checks that must
FAIL when the UI regresses. The tour's whole point is that the screenshots
and the checks see the same pixels:

- requested vs actual size: every resize made during the tour has its actual
  size recorded in index.txt next to the screenshot, and a size finding fires
  when the window/dialog can't shrink to what the tour asked for (a silently
  ignored resize made "0 clipping at small size" meaningless);
- RTL bidi: in fa, "650 ms" renders as "ms 650" unless isolated; every
  visible QLabel / button / table cell / menu action is screened for digit +
  Latin-unit runs that aren't wrapped in U+2066 (LRI) / U+2067 (RLI) /
  U+2068 (FSI) .. U+2069 (PDI) isolates;
- tooltips/accessible names: visible buttons need text or a tooltip, and
  icon-only buttons need an accessibleName too;
- every QDialog gets exactly one default button, Enter in a single-line field
  triggers it, and Enter in a QPlainTextEdit inserts a newline instead;
- faint checkboxes: each visible QCheckBox's indicator is grabbed and flagged
  when its luminance spread inside the indicator rect is under 40/255;
- a "needs a human look" section in findings.txt lists the shots a person
  must eyeball every run (fa tables, composed fa meta lines, the dense small
  size, and menus).

The tour is data-driven: `TOUR_STATES` is a list of State(name, description,
setup) entries, so pages of the upcoming sidebar window can be appended
without touching the check machinery. `--only <substring>` runs a subset,
`--lang en|fa|all` and `--size 1040x700|820x560|all` narrow the matrix.

NOT shipped: nothing under xrayui/ imports this, and PyInstaller's
Analysis in tools/build.spec only walks from app_main.py, so this file
is already outside every build's dependency graph.

Run:
    QT_QPA_PLATFORM=offscreen .venv/bin/python tools/ui_tour.py [out_dir]
        [--only <substring>] [--lang en|fa|all] [--size 1040x700|820x560|all]

Writes <out_dir>/<lang>/<size>/NN_<name>.png plus <out_dir>/index.txt and
<out_dir>/findings.txt. Every widget in the tour is fake: Connection,
network, metrics, xraycheck and every QMessageBox popup are stubbed before
the first window is built, so this never touches real routes, DNS, or a
system tray, needs no bundled xray binary, and never blocks on a modal.
"""
from __future__ import annotations

import argparse
import copy
import inspect
import os
import re
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QRect, Qt  # noqa: E402
from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QTableView,
    QWidget,
)

from xrayui.ui.pages import ServersPage  # noqa: E402

SIZES = [("1040x700", 1040, 700), ("820x560", 820, 560)]
LANGS = ["en", "fa"]
_FA_FONTS = '"Vazirmatn", "Noto Sans Arabic", "Segoe UI", "Tahoma", "Geeza Pro"'

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
_KIND_ORDER = ["size", "bidi", "a11y", "default-button", "checkbox", "clipping",
               "overlap", "off-window", "fa-leak", "tab-order", "esc-does-not-close"]

# A digit immediately followed by optional space and a Latin unit or letter
# run (ms, GB, MB, KB, Mbit/s, %, ...). In an RTL paragraph this pair
# reorders to "ms 650" unless the digits hang in a U+2066..U+2069 isolate.
_BIDI_RUN = re.compile(
    r"(?<![0-9A-Za-z\u0660-\u0669])"           # not glued to a letter/digit
    r"(?P<num>\d+(?:[.,]\d+)*)"
    r"\s*"
    r"(?P<unit>%|[A-Za-z]{1,8}(?:/[A-Za-z]{1,8})?)"
    r"(?![0-9A-Za-z])"
)


# -- stubs: nothing here may touch the real system --------------------------
def install_stubs() -> None:
    from PySide6.QtWidgets import QMessageBox

    from xrayui.core import connection as connection_mod
    from xrayui.core import hotspot, metrics, network, xraycheck
    from xrayui.core.xray import is_xray_running as _unused  # noqa: F401
    from xrayui.ui import main_window as mw

    class FakeConnection:
        def __init__(self, on_step=None) -> None:
            self._log = on_step or (lambda _m: None)
            self._connected = False
            self.state = _FakeState()

        def is_connected(self) -> bool:
            return self._connected

        def connect(self, profile) -> None:
            self._connected = True

        def disconnect(self) -> None:
            self._connected = False

        def cleanup(self) -> None:
            self._connected = False

        def recover_if_stale(self, dns_retries: int = 8) -> bool:
            return False

        def repair_route_if_needed(self):
            return None

        def repair_dns_if_needed(self):
            return None

        def stop_gateway(self):
            return None

    class _FakeState:
        alias = "Ethernet"
        ipv4 = "10.10.0.2"
        gateway = "10.10.0.1"
        tun_index = None  # keeps _sample_live() from firing

        def is_connected(self) -> bool:
            return False

    connection_mod.Connection = FakeConnection
    mw.Connection = FakeConnection
    mw.is_xray_running = lambda: False
    network.detect_interface = lambda: None
    hotspot.supported = lambda: False
    xraycheck.check_config = lambda *a, **k: None
    xraycheck.check_rules = lambda *a, **k: None
    metrics.ping = lambda *a, **k: "(stubbed)"
    metrics.tcp_connect_delay = lambda *a, **k: {"results": [], "avg": None, "min": None,
                                                 "max": None}
    metrics.throughput_sample = lambda *a, **k: None
    metrics.query_stats = lambda *a, **k: None
    metrics.baseline_sample = lambda *a, **k: None
    metrics.diagnostics = lambda *a, **k: "(stubbed)"

    # Enter-in-a-field below triggers real Save handlers; a validation warning
    # must record into the void instead of opening a modal the offscreen
    # platform can never close (the same trick tests/test_ui.py uses).
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    QMessageBox.critical = staticmethod(lambda *a, **k: None)
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)


# -- seed data ----------------------------------------------------------------
def seed_data(base_dir: Path, language: str) -> None:
    from xrayui import paths
    from xrayui.core import settings as app_settings
    from xrayui.core.profiles import Profile, ProfileStore
    from xrayui.core.speedtest import ResultStore
    from xrayui.core.subscription import Subscription, SubscriptionStore, Usage

    paths.base_dir = lambda: base_dir
    paths.state_dir = lambda: base_dir / "state"
    paths.profiles_dir = lambda: base_dir / "profiles"
    paths.ensure_dirs()

    settings = copy.deepcopy(app_settings.DEFAULTS)
    settings["language"] = language
    settings["routing"]["sets"] = [
        {
            "id": "set-1", "name": "Work rules", "domain_strategy": "",
            "rules": [
                {"remarks": "Ads blocked", "enabled": True, "outbound": "block",
                 "domain": ["geosite:category-ads-all"], "ip": [], "port": "",
                 "network": "", "protocol": [], "process": []},
                {"remarks": "LAN direct", "enabled": True, "outbound": "direct",
                 "domain": ["geosite:private"], "ip": ["geoip:private"], "port": "",
                 "network": "", "protocol": [], "process": []},
            ],
        },
        {
            "id": "set-2", "name": "Streaming", "domain_strategy": "IPIfNonMatch",
            "rules": [
                {"remarks": "Force proxy", "enabled": True, "outbound": "proxy",
                 "domain": ["netflix.com"], "ip": [], "port": "", "network": "",
                 "protocol": [], "process": []},
            ],
        },
    ]
    app_settings.save(settings)

    store = ProfileStore()
    profiles = {}
    profiles["reality"] = store.save(Profile(
        name="Frankfurt Reality", protocol="vless", address="de.example.com", port=443,
        id="11111111-1111-1111-1111-111111111111", network="tcp", security="reality",
        sni="www.microsoft.com", fp="chrome", pbk="MjJyOOxAQ0m9MJp368E7lLKmXQz0GBBpuF12E-B6H1Q",
        sid="ab",
    ))
    profiles["trojan"] = store.save(Profile(
        name="Amsterdam WS", protocol="trojan", address="nl.example.com", port=443,
        id="hunter2-password", network="ws", security="tls", sni="nl.example.com",
        path="/ws", host="nl.example.com",
    ))
    profiles["vmess"] = store.save(Profile(
        name="Tokyo gRPC", protocol="vmess", address="jp.example.com", port=443,
        id="22222222-2222-2222-2222-222222222222", network="grpc", security="tls",
        sni="jp.example.com", service_name="grpc-svc", vmess_security="auto",
    ))
    profiles["shadowsocks"] = store.save(Profile(
        name="Singapore SS", protocol="shadowsocks", address="sg.example.com", port=8388,
        id="s3cret-password", ss_method="2022-blake3-aes-256-gcm",
    ))
    profiles["hysteria2"] = store.save(Profile(
        name="London Hy2", protocol="hysteria2", address="uk.example.com", port=443,
        id="hy2-password", hy2_obfs_password="obfs-pw", hy2_ports="20000-30000",
    ))
    profiles["wireguard"] = store.save(Profile(
        name="Home WG", protocol="wireguard", address="1.2.3.4", port=51820,
        id="cHJpdmF0ZWtleWV4YW1wbGUxMjM0NTY3ODkwMTI=",
        pbk="cHVibGlja2V5ZXhhbXBsZTEyMzQ1Njc4OTAxMg==", wg_local_address="10.0.0.2/32",
    ))
    store.set_active(profiles["reality"].uid)

    results = ResultStore()
    results.set(profiles["reality"].uid, delay_ms=85.0, error=None, skipped=False)
    results.set(profiles["trojan"].uid, delay_ms=650.0, error=None, skipped=False)
    results.set(profiles["vmess"].uid, delay_ms=None, error="connection refused", skipped=False)
    results.set(profiles["shadowsocks"].uid, delay_ms=None, error="n/a (UDP)", skipped=True)
    # hysteria2 stays untested: no result recorded at all.
    results.set(profiles["wireguard"].uid, delay_ms=45.0, error=None, skipped=False)

    subs = SubscriptionStore()
    subs.save(Subscription(
        name="Main plan", url="https://sub.example.com/main", enabled=True,
        usage=Usage(upload=2_000_000_000, download=78_000_000_000, total=100_000_000_000,
                   expire=0),
        updated=time.time(),
    ))
    subs.save(Subscription(
        name="Old plan", url="https://sub.example.com/old", enabled=False,
    ))


# -- capture helpers ------------------------------------------------------
class Tour:
    def __init__(self, app: QApplication, out_dir: Path, lang: str, size_name: str) -> None:
        self.app = app
        self.dir = out_dir / lang / size_name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lang = lang
        self.size_name = size_name
        self._n = 0
        self.index_lines: list[str] = []
        # (severity, kind, where, text, dedup_key)
        self.findings: list[tuple[str, str, str, str, str]] = []
        self._dedup: set[tuple[str, str]] = set()
        self._shot_path = ""

    def state_begin(self) -> None:
        # "Report each offender once per state": a button that shows up twice
        # in one screen (two subscription rows) is still one offender.
        self._dedup.clear()

    def shot(self, widget: QWidget, name: str, note: str = "",
             expected: tuple[int | None, int | None] | None = None) -> Path:
        self._n += 1
        fname = f"{self._n:02d}_{name}.png"
        path = self.dir / fname
        self.app.processEvents()
        widget.grab().save(str(path))
        self._shot_path = f"{self.lang}/{self.size_name}/{fname}"
        actual = (widget.width(), widget.height())
        index_note = note or name
        if expected is not None:
            req_w, req_h = expected
            parts = []
            for axis, requested in (("width", req_w), ("height", req_h)):
                if requested is None:
                    continue
                parts.append(f"requested {axis} {requested}")
            index_note += " -- " + ", ".join(parts) + \
                f", actual {actual[0]}x{actual[1]}"
            if (req_w is not None and actual[0] > req_w) or \
                    (req_h is not None and actual[1] > req_h):
                over = []
                if req_w is not None and actual[0] > req_w:
                    over.append(f"width {req_w} -> {actual[0]}")
                if req_h is not None and actual[1] > req_h:
                    over.append(f"height {req_h} -> {actual[1]}")
                self.finding(
                    "high", "size", self._shot_path,
                    f"{type(widget).__name__} {name} requested "
                    f"{req_w or '-'}x{req_h or '-'} but rendered "
                    f"{actual[0]}x{actual[1]} ({'; '.join(over)}) "
                    f"(source: {_creating_source(widget)})",
                    key=f"size:{name}:{req_w or ''}x{req_h or ''}")
        self.index_lines.append(f"{self._shot_path} — {index_note}")
        self.check_widget(widget, self._shot_path)
        return path

    def finding(self, severity: str, kind: str, where: str, text: str,
                key: str | None = None) -> None:
        if key is None:
            key = f"{kind}:{where}:{text}"
        if (kind, key) in self._dedup:
            return
        self._dedup.add((kind, key))
        self.findings.append((severity, kind, where, text, key))

    # -- automated UX checks --------------------------------------------
    def check_widget(self, top: QWidget, shot_name: str) -> None:
        self._check_clipping(top, shot_name)
        self._check_off_window(top, shot_name)
        self._check_overlap(top, shot_name)
        self._check_icon_only_buttons(top, shot_name)
        if self.lang == "fa":
            self._check_english_leak(top, shot_name)
            self._check_bidi(top, shot_name)
        self._check_faded_checkboxes(top, shot_name)

    def _visible_labels_and_buttons(self, top: QWidget):
        for w in _find_children_of(top, QLabel, QPushButton, QCheckBox):
            if w.isVisible() and w.text().strip():
                yield w

    def _check_clipping(self, top: QWidget, shot_name: str) -> None:
        for w in self._visible_labels_and_buttons(top):
            if isinstance(w, QLabel) and w.wordWrap():
                continue  # wrapping labels are allowed to be narrower than sizeHint
            fm = QFontMetrics(w.font())
            text_w = fm.horizontalAdvance(w.text())
            avail = w.width()
            # Buttons/checkboxes need room for their own chrome (box, padding);
            # a small margin avoids flagging normal padding as clipping.
            margin = 24 if not isinstance(w, QLabel) else 4
            if avail > 0 and text_w > avail + margin:
                self.finding("medium", "clipping", shot_name,
                            f"{w.__class__.__name__} {w.objectName()!r} text={w.text()!r} "
                            f"needs ~{text_w}px, has {avail}px "
                            f"(source: {_creating_source(w, w.text())})")

    def _check_off_window(self, top: QWidget, shot_name: str) -> None:
        bounds = QRect(0, 0, top.width(), top.height())
        for w in top.findChildren(QWidget):
            if not w.isVisible() or w is top:
                continue
            if _inside_scroll_area(w, top):
                # Scrolled content legitimately extends past the viewport;
                # that's what the scrollbar is for, not a layout bug.
                continue
            r = QRect(w.mapTo(top, w.rect().topLeft()), w.size())
            if not bounds.contains(r):
                self.finding("high", "off-window", shot_name,
                            f"{w.__class__.__name__} {w.objectName()!r} at {r} "
                            f"exceeds {bounds} (source: {_creating_source(w)})")

    def _check_overlap(self, top: QWidget, shot_name: str) -> None:
        # Only compare siblings (same direct parent): a child legitimately
        # sits "inside" its parent's rect, which isn't overlap.
        seen: dict[int, list[tuple[QWidget, QRect]]] = {}
        for w in top.findChildren(QWidget):
            if not w.isVisible() or w.width() <= 0 or w.height() <= 0:
                continue
            parent = w.parentWidget()
            if parent is None:
                continue
            r = QRect(w.pos(), w.size())
            seen.setdefault(id(parent), []).append((w, r))
        for siblings in seen.values():
            for i in range(len(siblings)):
                wi, ri = siblings[i]
                for j in range(i + 1, len(siblings)):
                    wj, rj = siblings[j]
                    inter = ri.intersected(rj)
                    if inter.width() > 2 and inter.height() > 2:
                        self.finding("high", "overlap", shot_name,
                                    f"{wi.__class__.__name__} {wi.objectName()!r} overlaps "
                                    f"{wj.__class__.__name__} {wj.objectName()!r} by "
                                    f"{inter.width()}x{inter.height()}px")

    def _check_icon_only_buttons(self, top: QWidget, shot_name: str) -> None:
        for b in top.findChildren(QAbstractButton):
            if not b.isVisible():
                continue
            text = b.text().strip()
            tip = b.toolTip().strip()
            acc = b.accessibleName().strip()
            icon_only = not text or (len(text) <= 2 and not text.isalnum())
            if not text and not tip:
                self.finding("high", "a11y", shot_name,
                            f"{type(b).__name__} {b.objectName()!r} has no text and "
                            f"no tooltip (source: {_creating_source(b)})",
                            key=f"a11y-empty:{type(b).__name__}:{_creating_source(b)}")
                continue
            if not icon_only:
                continue
            if not tip:
                self.finding("high", "a11y", shot_name,
                            f"icon-only {type(b).__name__} {b.objectName()!r} "
                            f"text={text!r} has no tooltip "
                            f"(source: {_creating_source(b, text)})",
                            key=f"a11y-tip:{type(b).__name__}:{text}:{_creating_source(b, text)}")
            if not acc:
                self.finding("high", "a11y", shot_name,
                            f"icon-only {type(b).__name__} {b.objectName()!r} "
                            f"text={text!r} has no accessibleName "
                            f"(source: {_creating_source(b, text)})",
                            key=f"a11y-acc:{type(b).__name__}:{text}:{_creating_source(b, text)}")

    def _check_english_leak(self, top: QWidget, shot_name: str) -> None:
        for w in self._visible_labels_and_buttons(top):
            text = w.text()
            if _looks_like_untranslated_english(text):
                self.finding("medium", "fa-leak", shot_name,
                            f"{w.__class__.__name__} {w.objectName()!r} shows {text!r} "
                            f"in fa (source: {_creating_source(w, text)})")

    def _check_bidi(self, top: QWidget, shot_name: str) -> None:
        scored: dict[int, tuple[QWidget, list[str]]] = {}
        sources: dict[int, str] = {}
        for w in _find_children_of(top, QLabel, QAbstractButton):
            if not w.isVisible():
                continue
            text = w.text().strip()
            if not text or not w.isRightToLeft():
                continue
            bad = _unscoped_bidi_runs(text)
            if bad:
                scored.setdefault(id(w), (w, []))[1].extend(bad)
                sources[id(w)] = _creating_source(w, _bidi_token(text))
        for table in _find_children_of(top, QTableView):
            if not table.isVisible() or table.model() is None or not table.isRightToLeft():
                continue
            bad: list[str] = []
            for cell in _iter_visible_cell_texts(table):
                bad.extend(_unscoped_bidi_runs(cell))
            if bad:
                model_cls = type(table.model())
                sources[id(table)] = _class_file(model_cls) or \
                    f"{model_cls.__module__}.{model_cls.__qualname__}"
                scored.setdefault(id(table), (table, []))[1].extend(bad)
        menus = list(_find_children_of(top, QMenu))
        if isinstance(top, QMenu):
            menus.append(top)
        for m in menus:
            if not m.isVisible() or not m.isRightToLeft():
                continue
            bad = []
            for action in m.actions():
                bad.extend(_unscoped_bidi_runs(action.text()))
            if bad:
                scored.setdefault(id(m), (m, []))[1].extend(bad)
                sources[id(m)] = _creating_source(m)
        for _, (widget, runs) in scored.items():
            self.finding("high", "bidi", shot_name,
                        f"{type(widget).__name__} {widget.objectName()!r} mixes digits and "
                        f"Latin units without U+2066..U+2069 isolates: "
                        f"{', '.join(dict.fromkeys(runs))} (source: {sources[id(widget)]})",
                        key=f"bidi:{sources[id(widget)]}")

    def _check_faded_checkboxes(self, top: QWidget, shot_name: str) -> None:
        for cb in top.findChildren(QCheckBox):
            if not cb.isVisible() or not cb.isEnabled():
                continue  # a disabled box is intentionally dim, not a bug
            opt = QStyleOptionButton()
            cb.initStyleOption(opt)
            rect = cb.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, cb)
            img = cb.grab().toImage()
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            x1 = min(rect.x() + rect.width(), img.width())
            y1 = min(rect.y() + rect.height(), img.height())
            if x1 <= max(rect.x(), 0) or y1 <= max(rect.y(), 0):
                continue
            lums = []
            for yy in range(max(rect.y(), 0), y1):
                for xx in range(max(rect.x(), 0), x1):
                    c = img.pixelColor(xx, yy)
                    lums.append(0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue())
            if not lums:
                continue
            spread = max(lums) - min(lums)
            if spread < 40:
                self.finding("medium", "checkbox", shot_name,
                            f"QCheckBox {cb.text()!r} indicator is nearly invisible "
                            f"(luminance spread {spread:.0f}/255, needs >= 40) "
                            f"(source: {_creating_source(cb, cb.text())})",
                            key=f"checkbox:{_creating_source(cb, cb.text())}")

    def check_focus_order(self, dlg: QWidget, shot_name: str) -> None:
        expected = [w for w in _find_children_of(dlg, QLineEdit, QComboBox, QCheckBox,
                                                 QSpinBox, QPlainTextEdit)
                   if w.isVisible() and w.isEnabled() and w.focusPolicy() != Qt.NoFocus
                   # A QSpinBox's internal line edit is not a separate tab stop --
                   # Tab lands on the QSpinBox, which owns it as a focus proxy.
                   and w.objectName() != "qt_spinbox_lineedit"]
        if not expected:
            return
        reached: set[int] = set()
        first = expected[0]
        first.setFocus(Qt.OtherFocusReason)
        for _ in range(len(expected) * 3 + 5):
            self.app.processEvents()
            fw = self.app.focusWidget()
            if fw is not None:
                reached.add(id(fw))
            QTest.keyClick(dlg, Qt.Key_Tab)
        missing = [w for w in expected if id(w) not in reached]
        for w in missing:
            self.finding("medium", "tab-order", shot_name,
                        f"{w.__class__.__name__} {w.objectName()!r} never received focus "
                        f"by Tab (source: {_creating_source(w)})")

    def check_dialog_keyboard(self, dlg_factory, label: str) -> None:
        """Exactly one app-declared default button; Enter in a single-line
        field activates it (never in a plain-text field); Esc closes."""
        chosen_dlg = dlg_factory()
        chosen_buttons = [b for b in chosen_dlg.findChildren(QPushButton)
                          if b.isDefault()]
        chosen = chosen_buttons[0] if len(chosen_buttons) == 1 else None
        if len(chosen_buttons) != 1:
            found = ", ".join(sorted({b.text() for b in chosen_buttons}))
            self.finding("high", "default-button", "",
                         f"{label}: {type(chosen_dlg).__name__} must have exactly one "
                         f"default button, found {len(chosen_buttons)} ({found or 'none'})",
                         key=f"default-button:{label}")
        chosen_dlg.deleteLater()

        dlg = dlg_factory()
        dlg.show()
        self.app.processEvents()
        visible_buttons = [b for b in dlg.findChildren(QPushButton) if b.isVisible()]
        # On show Qt lets the first button that takes focus become the default,
        # silently overriding the button the app declared. Report that drift:
        # Enter in a text field then activates the wrong action (or none).
        shown_default = next((b for b in visible_buttons if b.isDefault()), None)
        if chosen is not None and \
                (shown_default is None or shown_default.text() != chosen.text()):
            self.finding("high", "default-drift", "",
                         f"{label}: {type(dlg).__name__} default {chosen.text()!r} at "
                         f"construction becomes {'none' if shown_default is None else shown_default.text()!r} "
                         f"when shown — Enter may activate the wrong action",
                         key=f"default-drift:{label}")

        # Re-declare the app-chosen default on the shown dialog so the focus
        # whirligig cannot reassign it mid-test, then assert what Enter does.
        target = None
        if chosen is not None:
            match = next((b for b in visible_buttons if b.text() == chosen.text()), None)
            if match is not None:
                for b in visible_buttons:
                    b.setAutoDefault(False)
                match.setAutoDefault(True)
                match.setDefault(True)
                target = match
        if target is not None:
            triggered: list[bool] = []
            target.clicked.connect(lambda: triggered.append(True))

            for w in _find_children_of(dlg, QPlainTextEdit):
                if not (w.isVisible() and w.isEnabled()):
                    continue
                w.setPlainText("")
                w.setFocus()
                self.app.processEvents()
                QTest.keyClick(w, Qt.Key_Return)
                self.app.processEvents()
                if triggered:
                    self.finding("high", "default-button", "",
                                 f"{label}: Enter in a QPlainTextEdit triggered the default "
                                 f"button {target.text()!r} (must insert a newline instead)",
                                 key=f"plain-enter:{label}")
                elif w.toPlainText() == "":
                    self.finding("high", "default-button", "",
                                 f"{label}: Enter in a QPlainTextEdit inserted nothing "
                                 f"(must insert a newline)",
                                 key=f"plain-enter:{label}")

            for w in _find_children_of(dlg, QLineEdit):
                if not (w.isVisible() and w.isEnabled()) or \
                        w.objectName() == "qt_spinbox_lineedit":
                    continue
                before = len(triggered)
                w.setFocus()
                self.app.processEvents()
                try:
                    QTest.keyClick(w, Qt.Key_Return)
                    self.app.processEvents()
                except Exception:
                    self.app.processEvents()
                if not triggered[before:] and dlg.isVisible():
                    self.finding("high", "default-button", "",
                                 f"{label}: Enter in a single-line field did not trigger the "
                                 f"default button {target.text()!r}",
                                 key=f"single-enter:{label}")
        dlg.close()
        dlg.deleteLater()

        dlg2 = dlg_factory()
        dlg2.show()
        self.app.processEvents()
        QTest.keyClick(dlg2, Qt.Key_Escape)
        self.app.processEvents()
        if dlg2.isVisible():
            self.finding("medium", "esc-does-not-close", "",
                         f"{label}: {type(dlg2).__name__} is still visible after Esc",
                         key=f"esc:{label}")
        dlg2.close()
        dlg2.deleteLater()


def _show_menu_at(menu: QMenu, global_pos) -> None:
    # menu.popup()/.exec() try to grab the keyboard/mouse for interactive
    # navigation, which the offscreen platform can't satisfy and which then
    # wedges the event loop waiting for a grab release that never comes.
    # A plain move()+show() renders the same thing without that dance.
    menu.move(global_pos)
    menu.show()


def _find_children_of(top: QWidget, *types: type) -> list[QWidget]:
    # PySide6's findChildren() takes exactly one type, not a tuple.
    out: list[QWidget] = []
    for t in types:
        out.extend(top.findChildren(t))
    return out


def _widget_source(w: QWidget) -> str:
    return f"{w.__class__.__module__}.{w.__class__.__qualname__}"


def _class_file(cls: type) -> str | None:
    try:
        src = inspect.getsourcefile(cls)
    except (OSError, TypeError):
        return None
    if not src:
        return None
    src = str(Path(src).resolve())
    # A widget defined in the app package is its own "creating file". Built-in
    # Qt widgets (plain QPushButton etc.) resolve nothing here.
    return src if src.startswith(str(ROOT)) else None


def _literal_line(path: str, token: str) -> int | None:
    needle = token.strip()
    if not needle:
        return None
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for i, line in enumerate(lines, 1):
        if needle in line:
            return i
    return None


def _creating_source(widget: QWidget, token: str | None = None) -> str:
    cls = type(widget)
    path = _class_file(cls)
    if path is None:
        # A raw QPushButton("✕") was created by one of xrayui/ui's classes;
        # report the nearest ancestor whose class lives in the app, which is
        # where a fix for the accessibility gap has to land.
        p = widget.parentWidget()
        while p is not None:
            path = _class_file(type(p))
            if path:
                break
            p = p.parentWidget()
    if path is None:
        return _widget_source(widget)
    if token:
        line = _literal_line(path, token)
        return f"{path}:{line}" if line else path
    return path


def _iter_visible_cell_texts(table: QTableView):
    model = table.model()
    viewport = table.viewport().rect()
    for row in range(model.rowCount()):
        for col in range(model.columnCount()):
            idx = model.index(row, col)
            vr = table.visualRect(idx)
            if vr.isEmpty() or not vr.intersects(viewport):
                continue
            data = model.data(idx, Qt.DisplayRole)
            if isinstance(data, str) and data.strip():
                yield data


def _isolate_intervals(text: str) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch in "\u2066\u2067\u2068":
            stack.append(i)
        elif ch == "\u2069" and stack:
            intervals.append((stack.pop(), i))
    return intervals


def _wrapped_in_isolate(text: str, start: int, end: int) -> bool:
    # The PDI sits at index e and the isolate covers [s+1, e-1], so a run
    # whose last char is right before the closer (end == e, e.g. "\u2066650
    # ms\u2069") is fully protected; requiring end < e would be a false hit.
    return any(s < start and end <= e for s, e in _isolate_intervals(text))


def _unscoped_bidi_runs(text: str) -> list[str]:
    return [m.group(0).strip() for m in _BIDI_RUN.finditer(text)
            if not _wrapped_in_isolate(text, m.start(), m.end())]


def _bidi_token(text: str) -> str | None:
    for m in _BIDI_RUN.finditer(text):
        return m.group("unit")
    return None


def _inside_scroll_area(w: QWidget, top: QWidget) -> bool:
    p = w.parentWidget()
    while p is not None and p is not top:
        if isinstance(p, QScrollArea):
            return True
        p = p.parentWidget()
    return False


_EN_WORDS = {
    "the", "and", "with", "your", "server", "servers", "connect", "disconnect",
    "settings", "routing", "subscription", "delete", "cancel", "save", "import",
    "export", "test", "edit", "add", "enabled", "disabled", "port", "address",
}


def _looks_like_untranslated_english(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    # Technical/proper nouns and units are allowed in fa by design (see
    # CLAUDE.md / the i18n coverage tests' own allowlist) -- only flag text
    # that reads as ordinary English prose a translator would recognize.
    words = [w.strip(".,:;()…—-").lower() for w in lower.split()]
    hits = sum(1 for w in words if w in _EN_WORDS)
    return hits >= 2


# -- the tour dictionary ---------------------------------------------------
@dataclass(frozen=True)
class State:
    name: str
    description: str
    setup: Callable[[Ctx], None]


class Ctx:
    """Shared, per-combo runtime handed to every State.setup. Pages of the
    sidebar UI only ever touch this and the Tour's shot()/checks."""

    def __init__(self, app: QApplication, tour: Tour, lang: str, size_name: str,
                 requested: tuple[int, int]) -> None:
        self.app = app
        self.tour = tour
        self.lang = lang
        self.size_name = size_name
        self.requested = requested
        self.i18n = None  # set by run_tour after set_language()
        self.win = None

    def ensure_window(self):
        if self.win is not None:
            return self.win
        from xrayui.ui.main_window import MainWindow
        win = MainWindow(elevated=True)
        win.resize(*self.requested)
        win.show()
        self.app.processEvents()
        self.win = win
        return win

    def shot(self, widget: QWidget, name: str, note: str = "",
             expected: tuple[int | None, int | None] | None = None) -> Path:
        return self.tour.shot(widget, name, note, expected=expected)


def _expand_advanced(app: QApplication, dlg: QWidget) -> None:
    from xrayui.ui.rule_editor import CollapsibleSection
    for section in dlg.findChildren(CollapsibleSection):
        section.set_expanded(True)
    app.processEvents()


# -- main window -----------------------------------------------------------
def _st_main_disconnected(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    win.alert_banner.setVisible(False)
    win.conn._connected = False
    win.btn_reconnect.setVisible(False)
    win._refresh_status()
    ctx.shot(win, "main_disconnected", "Main window, disconnected", expected=ctx.requested)


def _st_main_connected(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    win.alert_banner.setVisible(False)
    win.conn._connected = True
    win._needs_reconnect("Routing changed")
    win._refresh_status()
    ctx.shot(win, "main_connected_reconnect", "Fake-connected, Reconnect now visible",
             expected=ctx.requested)
    win.conn._connected = False
    win.btn_reconnect.setVisible(False)
    win._refresh_status()


def _st_main_alert(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    win._check_alerts()
    if not win.alert_banner.isVisible():
        win.alert_banner.show_alert(
            "warning", ctx.i18n.tr("Low data: {amount} left ({percent})",
                                   amount=ctx.i18n.ltr("22.0 GB"),
                                   percent=ctx.i18n.ltr("22%")))
    ctx.shot(win, "main_alert_banner", "Quota alert banner", expected=ctx.requested)


def _st_main_update(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    win.alert_banner.show_alert(
        "warning", ctx.i18n.tr("sushTun {tag} is available", tag="v9.9.9"),
        action_label=ctx.i18n.tr("Copy download link"), action=lambda: None,
    )
    ctx.shot(win, "main_update_banner", "Update-available banner", expected=ctx.requested)
    win.alert_banner.setVisible(False)


def _st_server_multiselect(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    sel_model = win.profiles.table.selectionModel()
    idx0 = win.profiles.proxy.index(0, 0)
    idx2 = win.profiles.proxy.index(2, 0)
    sel = QItemSelection(idx0, idx0)
    sel.select(idx2, idx2)
    sel_model.select(sel, QItemSelectionModel.Select | QItemSelectionModel.Rows)
    ctx.app.processEvents()
    ctx.shot(win.profiles, "server_table_multiselect", "Server table, two rows selected",
             expected=ctx.requested)


def _st_server_context_menu(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    if not win.profiles.selected_uids():
        sel_model = win.profiles.table.selectionModel()
        idx0 = win.profiles.proxy.index(0, 0)
        idx1 = win.profiles.proxy.index(1, 0)
        sel = QItemSelection(idx0, idx0)
        sel.select(idx1, idx1)
        sel_model.select(sel, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        ctx.app.processEvents()
    ctx_menu = win.profiles._build_context_menu(win.profiles.selected_uids())
    if ctx_menu is not None:
        _show_menu_at(ctx_menu, win.profiles.table.viewport().mapToGlobal(
            win.profiles.table.viewport().rect().center()))
        ctx.app.processEvents()
        ctx.shot(ctx_menu, "server_table_context_menu",
                 "Right-click menu on selected servers")
        ctx_menu.hide()


def _st_server_test_menu(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    test_menu = win.profiles.btn_test.menu()
    if test_menu is not None:
        _show_menu_at(test_menu, win.profiles.btn_test.mapToGlobal(
            win.profiles.btn_test.rect().bottomLeft()))
        ctx.app.processEvents()
        ctx.shot(test_menu, "server_table_test_menu", "Test ▾ menu")
        test_menu.hide()


def _st_server_more_menu(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    more_menu = win.profiles.btn_more.menu()
    if more_menu is not None:
        _show_menu_at(more_menu, win.profiles.btn_more.mapToGlobal(
            win.profiles.btn_more.rect().bottomLeft()))
        ctx.app.processEvents()
        ctx.shot(more_menu, "server_table_more_menu", "⋯ menu")
        more_menu.hide()


def _st_server_header_menu(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    header_menu = win.profiles._build_header_menu()
    _show_menu_at(header_menu, win.profiles.table.mapToGlobal(
        win.profiles.table.rect().topLeft()))
    ctx.app.processEvents()
    ctx.shot(header_menu, "server_table_header_menu", "Column visibility menu")
    header_menu.hide()


def _st_server_filter(ctx: Ctx) -> None:
    win = ctx.ensure_window()
    win.profiles.table.selectionModel().clearSelection()
    QTest.keyClicks(win.profiles.filter_edit, "Frankfurt")
    ctx.app.processEvents()
    ctx.shot(win.profiles, "server_table_filter", "Filter text typed", expected=ctx.requested)
    win.profiles.filter_edit.clear()
    ctx.app.processEvents()


# -- sidebar pages ---------------------------------------------------------
def _page_shot(ctx: Ctx, page: QWidget, name: str, note: str) -> None:
    # The pages live inside the sidebar window's content scroll area; the
    # content column is the window minus a 244px sidebar. Rendering through
    # the same scroll host keeps the tour's size checks honest at these
    # widths (576 / 796) and lets a page that can't shrink below its min
    # show its real scrollbar rather than a bogus "clipping" finding.
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout
    content_w = ctx.requested[0] - 244
    content_h = ctx.requested[1]
    # Wrap the scroll area in a container so the off-window check sees the
    # scroll area as a child of the container and correctly treats its
    # descendants as "inside a scroll area".
    container = QWidget()
    lay = QVBoxLayout(container)
    lay.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(page)
    lay.addWidget(scroll)
    container.resize(content_w, content_h)
    container.show()
    ctx.app.processEvents()
    ctx.shot(container, name, note, expected=(content_w, content_h))
    container.close()


def _build_servers_page() -> ServersPage:
    from xrayui.core.profiles import ProfileStore
    from xrayui.core.speedtest import ResultStore
    from xrayui.core.subscription import SubscriptionStore
    from xrayui.ui.pages import ServersPage
    store = ProfileStore()
    profiles = store.list()
    results = {}
    result_store = ResultStore()
    for p in profiles:
        card = result_store.get(p.uid)
        if card:
            results[p.uid] = card
    sub_names = {}
    for sub in SubscriptionStore().list():
        for uid in sub.profile_uids:
            sub_names[uid] = sub.name
    page = ServersPage()
    page.set_profiles(profiles, store.active_uid())
    page.set_results(results)
    page.set_sub_names(sub_names)
    page.set_connected(False)
    return page


def _st_pages_servers(ctx: Ctx) -> None:
    _page_shot(ctx, _build_servers_page(), "pages_servers",
               "Servers page, disconnected")


def _st_pages_servers_connected(ctx: Ctx) -> None:
    page = _build_servers_page()
    page.set_connected(True)
    page.set_connection("throughput", "↓ 42.3 ↑ 8.1 Mbit/s")
    page.set_connection("used", "18.6 GB")
    page.set_connection("delay", "650 ms")
    page.header.set_timer("42:10")
    _page_shot(ctx, page, "pages_servers_connected",
               "Servers page, connected header")


def _st_pages_servers_filter(ctx: Ctx) -> None:
    page = _build_servers_page()
    page.set_filter_text("Frankfurt")
    _page_shot(ctx, page, "pages_servers_filter",
               "Servers page, filter text typed")


def _st_pages_subscriptions(ctx: Ctx) -> None:
    from xrayui.core.subscription import SubscriptionStore
    from xrayui.ui.pages import SubscriptionsPage
    page = SubscriptionsPage()
    page.set_subscriptions(SubscriptionStore().list())
    _page_shot(ctx, page, "pages_subscriptions",
               "Subscriptions page with seeded plans")


def _st_pages_activity_log(ctx: Ctx) -> None:
    from xrayui.ui.pages import ActivityPage
    page = ActivityPage()
    for line in ("[tun] route 10.0.0.0/8 dev utun3",
                 "[dns] nameservers in the tunnel",
                 "[sys] connected — 42% of quota left"):
        page.append_log(line)
    _page_shot(ctx, page, "pages_activity_log", "Activity page, Live log")


def _st_pages_activity_tools(ctx: Ctx) -> None:
    from xrayui.ui.pages import ActivityPage
    page = ActivityPage()
    page.tabs.setCurrentIndex(1)
    page.tools.set_result("ping de.example.com 8/8\navg 84 ms")
    _page_shot(ctx, page, "pages_activity_tools", "Activity page, Tools")


def _st_pages_activity_diagnostics(ctx: Ctx) -> None:
    from xrayui.ui.pages import ActivityPage
    page = ActivityPage()
    page.tabs.setCurrentIndex(2)
    page.diagnostics.set_detail("process", "xray 92934 (v1.8.13)")
    page.diagnostics.set_detail("iface", "tun0 / Ethernet")
    page.diagnostics.set_detail("ip", "10.10.0.2 / 192.168.1.42")
    page.diagnostics.set_detail("gateway", "10.10.0.1")
    page.diagnostics.set_detail("tun", "utun3")
    page.diagnostics.set_output(
        "process: xray 92934\ninterface: tun0 (tun)\ntun_index: 3\ngateway: 10.10.0.1")
    _page_shot(ctx, page, "pages_activity_diagnostics",
               "Activity page, Diagnostics readout")


def _st_pages_sidebar_subs(ctx: Ctx) -> None:
    from xrayui.core.subscription import SubscriptionStore
    from xrayui.ui.pages import SidebarSubscriptionList
    lst = SidebarSubscriptionList()
    lst.set_subscriptions(SubscriptionStore().list())
    _page_shot(ctx, lst, "pages_sidebar_subs",
               "Sidebar subscription list (enabled plans only)")


def _tray_menus(ctx: Ctx):
    win = ctx.ensure_window()
    win.servers_menu = QMenu()
    win.routing_menu = QMenu()
    win._rebuild_servers_tray_menu()
    win._rebuild_routing_tray_menu()
    return win


def _st_tray_menu(ctx: Ctx) -> None:
    win = _tray_menus(ctx)
    top_tray_menu = QMenu()
    top_tray_menu.addAction(ctx.i18n.tr("Show"))
    top_tray_menu.addAction(ctx.i18n.tr("Connect"))
    top_tray_menu.addAction(ctx.i18n.tr("Disconnect"))
    top_tray_menu.addSeparator()
    servers_sub = top_tray_menu.addMenu(ctx.i18n.tr("Servers"))
    for a in win.servers_menu.actions():
        servers_sub.addAction(a)
    routing_sub = top_tray_menu.addMenu(ctx.i18n.tr("Routing"))
    for a in win.routing_menu.actions():
        routing_sub.addAction(a)
    top_tray_menu.addSeparator()
    top_tray_menu.addAction(ctx.i18n.tr("Quit"))
    _show_menu_at(top_tray_menu, win.mapToGlobal(win.rect().topLeft()))
    ctx.app.processEvents()
    ctx.shot(top_tray_menu, "tray_menu", "Tray icon menu")
    top_tray_menu.hide()


def _st_tray_servers_submenu(ctx: Ctx) -> None:
    win = _tray_menus(ctx)
    _show_menu_at(win.servers_menu, win.mapToGlobal(win.rect().topLeft()))
    ctx.app.processEvents()
    ctx.shot(win.servers_menu, "tray_servers_submenu", "Tray Servers submenu")
    win.servers_menu.hide()


def _st_tray_routing_submenu(ctx: Ctx) -> None:
    win = _tray_menus(ctx)
    _show_menu_at(win.routing_menu, win.mapToGlobal(win.rect().topLeft()))
    ctx.app.processEvents()
    ctx.shot(win.routing_menu, "tray_routing_submenu", "Tray Routing submenu")
    win.routing_menu.hide()


# -- dialogs ----------------------------------------------------------------
def _st_import_dialog(ctx: Ctx) -> None:
    from xrayui.ui.dialogs import ImportDialog
    win = ctx.ensure_window()
    w, h = ctx.requested
    dlg = ImportDialog(win)
    dlg.resize(w - 100, h - 150)
    dlg.show()
    for i in range(dlg.tabs.count()):
        dlg.tabs.setCurrentIndex(i)
        ctx.app.processEvents()
        ctx.shot(dlg, f"import_dialog_tab{i}",
                 f"Import dialog, tab {dlg.tabs.tabText(i)}",
                 expected=(w - 100, h - 150))
    ctx.tour.check_focus_order(dlg, "import_dialog")
    dlg.close()


def _st_profile_editors(ctx: Ctx) -> None:
    from xrayui.ui.dialogs import ProfileEditDialog
    win = ctx.ensure_window()
    w, h = ctx.requested
    for profile in win.store.list():
        dlg = ProfileEditDialog(profile, win)
        dlg.resize(w - 100, h - 80)
        dlg.show()
        _expand_advanced(ctx.app, dlg)
        ctx.shot(dlg, f"profile_edit_{profile.protocol}",
                 f"Profile editor, {profile.protocol}, Advanced expanded",
                 expected=(w - 100, h - 80))
        if profile.protocol == "vless":
            ctx.tour.check_focus_order(dlg, "profile_edit_vless")
        dlg.close()


def _st_settings(ctx: Ctx) -> None:
    from xrayui.ui.dialogs import SettingsDialog
    win = ctx.ensure_window()
    w, h = ctx.requested
    dlg = SettingsDialog(win.settings, win)
    dlg.resize(min(w - 100, 460), h - 60)
    dlg.show()
    _expand_advanced(ctx.app, dlg)
    scroll = dlg.findChild(QScrollArea)
    if scroll is not None:
        sb = scroll.verticalScrollBar()
        sb.setValue(sb.minimum())
        ctx.app.processEvents()
        ctx.shot(dlg, "settings_top", "Settings, scrolled to top",
                 expected=(min(w - 100, 460), h - 60))
        sb.setValue((sb.minimum() + sb.maximum()) // 2)
        ctx.app.processEvents()
        ctx.shot(dlg, "settings_middle", "Settings, scrolled to middle",
                 expected=(min(w - 100, 460), h - 60))
        sb.setValue(sb.maximum())
        ctx.app.processEvents()
        ctx.shot(dlg, "settings_bottom", "Settings, scrolled to bottom",
                 expected=(min(w - 100, 460), h - 60))
    else:
        ctx.shot(dlg, "settings", "Settings dialog", expected=(min(w - 100, 460), h - 60))
    ctx.tour.check_focus_order(dlg, "settings_dialog")
    dlg.close()


def _st_settings_window(ctx: Ctx) -> None:
    from xrayui.ui.settings_window import TOPICS, SettingsWindow
    win = ctx.ensure_window()
    dlg = SettingsWindow(win.settings, win)
    dlg.resize(820, 560)
    dlg.show()
    ctx.app.processEvents()

    for key, label, _icon, _color in TOPICS:
        dlg._select_topic(key)
        ctx.app.processEvents()
        ctx.shot(dlg, f"settings_{key}", f"Settings — {label}",
                 expected=(820, 560))

    # Focus order across a field-dense topic page.
    dlg._select_topic("general")
    ctx.app.processEvents()
    ctx.tour.check_focus_order(dlg, "settings_window")
    dlg.close()


def _st_routing_simple(ctx: Ctx) -> None:
    from xrayui.ui.routing_dialog import RoutingDialog
    win = ctx.ensure_window()
    w, h = ctx.requested
    dlg = RoutingDialog(win.settings["routing"], win)
    dlg.resize(w - 60, h - 60)
    dlg.show()
    dlg.tabs.setCurrentIndex(0)
    ctx.app.processEvents()
    ctx.shot(dlg, "routing_simple", "Routing dialog, Simple tab", expected=(w - 60, h - 60))
    ctx.tour.check_focus_order(dlg, "routing_dialog")
    dlg.close()


def _st_routing_rule_sets(ctx: Ctx) -> None:
    from xrayui.ui.routing_dialog import RoutingDialog
    win = ctx.ensure_window()
    w, h = ctx.requested
    dlg = RoutingDialog(win.settings["routing"], win)
    dlg.resize(w - 60, h - 60)
    dlg.show()
    dlg.tabs.setCurrentIndex(1)
    if dlg.sets_list.count():
        dlg.sets_list.setCurrentRow(0)
    ctx.app.processEvents()
    ctx.shot(dlg, "routing_rule_sets", "Routing dialog, Rule sets tab", expected=(w - 60, h - 60))
    dlg.close()


def _st_rule_editor(ctx: Ctx) -> None:
    from xrayui.ui.rule_editor import RuleEditorDialog, default_rule
    win = ctx.ensure_window()
    w, h = ctx.requested
    dlg = RuleEditorDialog(default_rule(), win)
    dlg.resize(min(w - 100, 480), h - 100)
    dlg.show()
    ctx.app.processEvents()
    ctx.shot(dlg, "rule_editor", "Rule editor", expected=(min(w - 100, 480), h - 100))
    ctx.tour.check_focus_order(dlg, "rule_editor")
    dlg.close()


def _st_dns_dialog(ctx: Ctx) -> None:
    from xrayui.ui.dns_dialog import DnsDialog
    win = ctx.ensure_window()
    w, h = ctx.requested
    dlg = DnsDialog(win.settings["dns"], win.settings["routing"], win)
    dlg.resize(min(w - 60, 560), h - 40)
    dlg.show()
    _expand_advanced(ctx.app, dlg)
    ctx.app.processEvents()
    ctx.shot(dlg, "dns_dialog", "DNS dialog, Advanced expanded",
             expected=(min(w - 60, 560), h - 40))
    ctx.tour.check_focus_order(dlg, "dns_dialog")
    dlg.close()


def _st_subscription_edit(ctx: Ctx) -> None:
    from xrayui.core.subscription import Subscription
    from xrayui.ui.dialogs import SubscriptionEditDialog
    win = ctx.ensure_window()
    w, h = ctx.requested
    dlg = SubscriptionEditDialog(Subscription(name="Main plan",
                                              url="https://sub.example.com/main"), win)
    dlg.resize(min(w - 100, 420), dlg.sizeHint().height())
    dlg.show()
    ctx.app.processEvents()
    ctx.shot(dlg, "subscription_edit", "Subscription editor",
             expected=(min(w - 100, 420), None))
    ctx.tour.check_focus_order(dlg, "subscription_edit")
    dlg.close()


def _st_qr_dialog(ctx: Ctx) -> None:
    from xrayui.ui.server_table import QrDialog
    ctx.ensure_window()
    qr_dlg = QrDialog("Frankfurt Reality",
                      "vless://11111111-1111-1111-1111-111111111111@de.example.com:"
                      "443?type=tcp&security=reality&sni=www.microsoft.com&fp=chrome"
                      "&pbk=MjJyOOxAQ0m9MJp368E7lLKmXQz0GBBpuF12E-B6H1Q&sid=ab#Frankfurt")
    qr_dlg.show()
    ctx.app.processEvents()
    ctx.shot(qr_dlg, "qr_dialog", "Share-link QR dialog")
    qr_dlg.close()


def _st_default_buttons(ctx: Ctx) -> None:
    from xrayui.core.subscription import Subscription
    from xrayui.ui.dialogs import (
        ImportDialog,
        ProfileEditDialog,
        SettingsDialog,
        SubscriptionEditDialog,
    )
    from xrayui.ui.dns_dialog import DnsDialog
    from xrayui.ui.routing_dialog import RoutingDialog
    from xrayui.ui.rule_editor import RuleEditorDialog, default_rule
    from xrayui.ui.server_table import QrDialog
    from xrayui.ui.settings_window import SettingsWindow

    win = ctx.ensure_window()
    checks = [
        (lambda: SettingsDialog(win.settings, win), "settings_dialog"),
        (lambda: SettingsWindow(win.settings, win), "settings_window"),
        (lambda: DnsDialog(win.settings["dns"], win.settings["routing"], win), "dns_dialog"),
        (lambda: RoutingDialog(win.settings["routing"], win), "routing_dialog"),
        (lambda: RuleEditorDialog(default_rule(), win), "rule_editor"),
        (lambda: ProfileEditDialog(win.store.list()[0], win), "profile_edit"),
        (lambda: SubscriptionEditDialog(Subscription(name="Main plan",
                                                     url="https://sub.example.com/main"),
                                        win),
         "subscription_edit"),
        (lambda: ImportDialog(win), "import_dialog"),
        (lambda: QrDialog("Frankfurt Reality", "vless://x@y:443#f"), "qr_dialog"),
    ]
    for factory, label in checks:
        ctx.tour.check_dialog_keyboard(factory, label)


TOUR_STATES: list[State] = [
    State("main_disconnected", "Main window, disconnected", _st_main_disconnected),
    State("main_connected_reconnect", "Fake-connected, Reconnect now visible", _st_main_connected),
    State("main_alert_banner", "Quota alert banner", _st_main_alert),
    State("main_update_banner", "Update-available banner", _st_main_update),
    State("server_table_multiselect", "Server table, two rows selected", _st_server_multiselect),
    State("server_table_context_menu", "Right-click menu on selected servers",
          _st_server_context_menu),
    State("server_table_test_menu", "Test ▾ menu", _st_server_test_menu),
    State("server_table_more_menu", "⋯ menu", _st_server_more_menu),
    State("server_table_header_menu", "Column visibility menu", _st_server_header_menu),
    State("server_table_filter", "Filter text typed", _st_server_filter),
    State("tray_menu", "Tray icon menu", _st_tray_menu),
    State("tray_servers_submenu", "Tray Servers submenu", _st_tray_servers_submenu),
    State("tray_routing_submenu", "Tray Routing submenu", _st_tray_routing_submenu),
    State("import_dialog", "Import dialog, every tab", _st_import_dialog),
    State("profile_editors", "Profile editor per protocol, Advanced expanded",
          _st_profile_editors),
    State("settings", "Settings dialog, scrolled top/middle/bottom", _st_settings),
    State("settings_window", "System-settings SettingsWindow, all topics", _st_settings_window),
    State("routing_simple", "Routing dialog, Simple tab", _st_routing_simple),
    State("routing_rule_sets", "Routing dialog, Rule sets tab", _st_routing_rule_sets),
    State("rule_editor", "Rule editor", _st_rule_editor),
    State("dns_dialog", "DNS dialog, Advanced expanded", _st_dns_dialog),
    State("subscription_edit", "Subscription editor", _st_subscription_edit),
    State("qr_dialog", "Share-link QR dialog", _st_qr_dialog),
    State("default_buttons", "Every dialog has a default button; Enter/Esc behaviour",
          _st_default_buttons),
    State("pages_servers", "Servers page, disconnected", _st_pages_servers),
    State("pages_servers_connected", "Servers page, connected header",
          _st_pages_servers_connected),
    State("pages_servers_filter", "Servers page, filter text typed", _st_pages_servers_filter),
    State("pages_subscriptions", "Subscriptions page", _st_pages_subscriptions),
    State("pages_activity_log", "Activity page, Live log segment", _st_pages_activity_log),
    State("pages_activity_tools", "Activity page, Tools segment", _st_pages_activity_tools),
    State("pages_activity_diagnostics", "Activity page, Diagnostics readout",
          _st_pages_activity_diagnostics),
    State("pages_sidebar_subs", "Sidebar subscription list", _st_pages_sidebar_subs),
]


def _format_finding(sev: str, kind: str, where: str, text: str) -> str:
    where_part = f"{where}: " if where else ""
    return f"[{sev}] {kind}: {where_part}{text}"


def _human_look_from_index(index_lines: list[str]) -> list[str]:
    # The shots a person must eyeball every run: fa tables (the "ms 650"
    # scramble), composed fa meta lines (subscription/status rows), the dense
    # dialogs at the small size, and every menu.
    out: set[str] = set()
    for line in index_lines:
        path = line.split(" — ", 1)[0].strip()
        parts = path.split("/")
        if len(parts) != 3:
            continue
        lang, size, fname = parts
        if lang == "fa" and "server_table" in fname:
            out.add(path)
        if lang == "fa" and (fname.startswith("main_") or "subscription" in fname):
            out.add(path)
        if size == "820x560":
            out.add(path)
        if "menu" in fname or "submenu" in fname:
            out.add(path)
    return sorted(out)


def write_outputs(out_dir: Path, findings: list[tuple], index_lines: list[str]) -> None:
    raw = sorted(
        findings,
        key=lambda f: (_SEVERITY_RANK.get(f[0], 9),
                       _KIND_ORDER.index(f[1]) if f[1] in _KIND_ORDER else 99,
                       f[2], f[3]),
    )

    groups: dict[tuple[str, str, str], list[tuple]] = defaultdict(list)
    for f in raw:
        groups[(f[1], f[4], f[3])].append(f)

    summary: list[str] = []
    for (kind, _key, text), entries in sorted(
            groups.items(),
            key=lambda kv: (_KIND_ORDER.index(kv[0][0]) if kv[0][0] in _KIND_ORDER else 99,
                            kv[1][0][3])):
        # Default-button/style findings are recorded with an empty `where`, so
        # they carry no language/size context; those groups get no span clause.
        langs = {e[2].split("/")[0] for e in entries if "/" in e[2]}
        sizes = {e[2].split("/")[1] for e in entries if e[2].count("/") >= 2}
        span = ""
        if langs:
            span = f" across {len(langs)} lang(s) / {len(sizes) or '?'} size(s)"
        first = entries[0]
        summary.append(
            f"{kind} [{first[0]}]: {len(entries)} finding(s){span} -- {text}")

    lines = ["# Findings", ""]
    lines.extend(_format_finding(*f[:4]) for f in raw)
    lines += ["", "# Deduplicated summary (offenders counted once per state, "
              "collapsed across languages and sizes)", ""]
    lines.extend(summary)
    lines += ["", "# Screenshots that need a human look", ""]
    for p in _human_look_from_index(index_lines):
        lines.append(f"- {p}")
    (out_dir / "findings.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    (out_dir / "index.txt").write_text("\n".join(index_lines) + "\n", encoding="utf-8")


def run_tour(out_dir: Path, states: list[State] | None = None,
             langs: list[str] | None = None,
             sizes: list[tuple[str, int, int]] | None = None) -> list[str]:
    from xrayui import i18n
    from xrayui.ui import theme

    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    install_stubs()
    states = list(states) if states else list(TOUR_STATES)
    langs = list(langs) if langs else list(LANGS)
    sizes = list(sizes) if sizes else list(SIZES)

    all_findings: list[tuple] = []
    all_index: list[str] = []

    for lang in langs:
        for size_name, w, h in sizes:
            base_dir = Path(tempfile.mkdtemp(prefix=f"ui_tour_{lang}_{size_name}_"))
            seed_data(base_dir, lang)
            i18n.set_language(lang)
            if lang == "fa":
                app.setLayoutDirection(Qt.RightToLeft)
                app.setStyleSheet(theme.build_stylesheet(f"{_FA_FONTS}, {theme._FONT}"))
            else:
                app.setLayoutDirection(Qt.LeftToRight)
                app.setStyleSheet(theme.STYLESHEET)

            tour = Tour(app, out_dir, lang, size_name)
            ctx = Ctx(app, tour, lang, size_name, (w, h))
            ctx.i18n = i18n
            for state in states:
                tour.state_begin()
                state.setup(ctx)
            if ctx.win is not None:
                ctx.win.tailer.stop()
                ctx.win.close()
                ctx.win.deleteLater()
                ctx.win = None
            app.processEvents()
            shutil.rmtree(base_dir, ignore_errors=True)

            all_findings.extend(tour.findings)
            all_index.extend(tour.index_lines)

    write_outputs(out_dir, all_findings, all_index)
    return [_format_finding(*f[:4]) for f in all_findings]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scripted offscreen UI tour with automatic UX checks.")
    parser.add_argument("out_dir", nargs="?", default="ui_tour_out",
                        help="output directory for screenshots and reports")
    parser.add_argument("--only", default=None,
                        help="run only states whose name contains this substring")
    parser.add_argument("--lang", default="all", choices=["en", "fa", "all"])
    parser.add_argument("--size", default="all", choices=["1040x700", "820x560", "all"])
    args = parser.parse_args()

    if args.only:
        states = [s for s in TOUR_STATES if args.only in s.name]
        if not states:
            print("no states match --only; available:",
                  ", ".join(s.name for s in TOUR_STATES))
            return 1
    else:
        states = list(TOUR_STATES)
    langs = ["en", "fa"] if args.lang == "all" else [args.lang]
    sizes = SIZES if args.size == "all" else [s for s in SIZES if s[0] == args.size]

    out_dir = Path(args.out_dir)
    findings = run_tour(out_dir, states=states, langs=langs, sizes=sizes)
    print(f"{len(findings)} findings written to {out_dir / 'findings.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
