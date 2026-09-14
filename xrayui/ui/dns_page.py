"""DNS editor as an embeddable page: resolvers, static overrides, domestic
DNS, remote-via-tunnel resolution, and advanced overrides, plus dirty
tracking, revert and an off-thread apply for the sidebar window. The
DnsDialog is a thin wrapper around this page (see dns_dialog.py).

apply() refuses malformed fields inline (in the page's status label, where
a modal box would throw the sidebar user off the page) and, like the old
dialog's Save, renders the real config (a placeholder profile, current
routing, candidate DNS) and validates it via the real Xray binary before
the result is committed.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import dns as dns_mod
from ..core import render, xraycheck
from ..core import routing as routing_mod
from ..core.profiles import Profile
from ..i18n import tr
from .rule_editor import CollapsibleSection
from .workers import Worker

_CHECK_PROFILE = Profile(
    name="dns check", protocol="vless", address="203.0.113.1", port=443,
    id="11111111-1111-1111-1111-111111111111", encryption="none",
    network="tcp", security="none",
)


def _ltr(text: str) -> str:
    """LTR-isolate `text` (a resolver address) so Persian RTL layout renders
    it left-to-right inside the translated reason. U+2066/U+2069 are the
    Unicode bidirectional-isolation marks, honoured by Qt's text shaping.
    Another worker is adding i18n.ltr(); this local copy exists so the two
    can be unified at merge."""
    return f"\u2066{text}\u2069"


class DnsPage(QWidget):
    """The DNS editor as a page: dirty-tracking, revert, off-thread apply.

    Signals:
        dirtyChanged(bool): emitted whenever a field differs from the state
            load() was last given (and when it stops differing).
        applied(object): the candidate DNS dict, after apply()'s render +
            Xray validation succeeded off the UI thread.
        applyFinished(bool): True when apply() applied the page, False when
            a refusal (a malformed field or a validation failure) left it
            dirty.
    """
    dirtyChanged = Signal(bool)
    applied = Signal(object)
    applyFinished = Signal(bool)

    def __init__(self, dns: dict, routing_cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._dns = dict(dns)
        self._routing_cfg = routing_cfg
        self._loaded_routing = dict(routing_cfg)
        self._busy = False
        self._dirty = False
        self._loading = True  # construction populates widgets; see @end
        self.pool = QThreadPool.globalInstance()
        self._workers: set = set()

        layout = QVBoxLayout(self)

        presets = QHBoxLayout()
        presets.addWidget(QLabel(tr("Preset:")))
        for name, servers in dns_mod.PRESETS.items():
            btn = QPushButton(name)
            btn.clicked.connect(lambda _=False, s=servers: self._fill(s))
            presets.addWidget(btn)
        presets.addStretch(1)
        layout.addLayout(presets)

        layout.addWidget(QLabel(tr("Resolvers (one per line, in order):")))
        self.servers = QPlainTextEdit("\n".join(dns.get("servers") or []))
        self.servers.setPlaceholderText(
            tr("Leave empty to keep the template's servers.") + "\n"
            "https://1.1.1.1/dns-query\n"
            "tcp://9.9.9.9:53\n"
            "8.8.8.8\n"
            + tr("Use literal IPs — a hostname needs another resolver to look it up first.")
        )
        self.servers.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(self.servers, 2)

        strategy = QHBoxLayout()
        strategy.addWidget(QLabel(tr("Query strategy:")))
        self.strategy = QComboBox()
        self.strategy.addItem(tr("Template default"), "")
        for name in dns_mod.QUERY_STRATEGIES:
            self.strategy.addItem(name, name)
        current = str(dns.get("query_strategy") or "")
        self.strategy.setCurrentIndex(max(0, self.strategy.findData(current)))
        self.strategy.setToolTip(
            tr("UseIPv4 avoids AAAA answers this IPv4-only tunnel cannot route.") + "\n"
            + tr("UseIP or UseIPv6 can make clients prefer an IPv6 path that leaves\n"
                 "over your physical adapter instead of the tunnel.")
        )
        strategy.addWidget(self.strategy, 1)
        layout.addLayout(strategy)

        layout.addWidget(QLabel(tr("Static overrides (domain = address):")))
        self.hosts = QPlainTextEdit("\n".join(dns.get("hosts") or []))
        self.hosts.setPlaceholderText(
            "example.com = 93.184.216.34\ncdn.example.com = 1.2.3.4, 5.6.7.8")
        self.hosts.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(self.hosts, 1)

        # -- Domestic DNS ----------------------------------------------
        dom_label = QLabel(tr("Domestic DNS (for sites that go direct):"))
        dom_label.setToolTip(tr("Used only for domains your active routing sends direct."))
        layout.addWidget(dom_label)
        dom_row = QHBoxLayout()
        self.domestic = QLineEdit(", ".join(dns.get("domestic_servers") or []))
        self.domestic.setPlaceholderText("178.22.122.100, 185.51.200.2")
        self.domestic.setToolTip(tr("Used only for domains your active routing sends direct."))
        self.domestic.setLayoutDirection(Qt.LeftToRight)
        dom_row.addWidget(self.domestic, 1)
        for name, addrs in dns_mod.DOMESTIC_PRESETS.items():
            btn = QPushButton(name)
            btn.clicked.connect(lambda _=False, a=addrs: self._fill_domestic(a))
            dom_row.addWidget(btn)
        off_btn = QPushButton(tr("Off"))
        off_btn.clicked.connect(lambda: self._fill_domestic([]))
        dom_row.addWidget(off_btn)
        layout.addLayout(dom_row)

        # -- Remote via tunnel -------------------------------------------
        self.remote_via_tunnel = QCheckBox(tr("Resolve other sites through the tunnel"))
        self.remote_via_tunnel.setToolTip(
            tr("Recommended if your ISP blocks or tampers with DNS."))
        self.remote_via_tunnel.setChecked(bool(dns.get("remote_via_tunnel")))
        self.remote_via_tunnel.toggled.connect(self._update_note)
        layout.addWidget(self.remote_via_tunnel)

        self.note = QLabel()
        self.note.setObjectName("Muted")
        layout.addWidget(self.note)
        self._update_note()

        # -- Advanced ---------------------------------------------------
        adv_widget = QWidget()
        adv = QVBoxLayout(adv_widget)
        adv.setContentsMargins(0, 4, 0, 0)
        self.parallel_query = QCheckBox(tr("Parallel query"))
        self.parallel_query.setChecked(bool(dns.get("parallel_query")))
        adv.addWidget(self.parallel_query)
        self.serve_stale = QCheckBox(tr("Serve stale"))
        self.serve_stale.setChecked(bool(dns.get("serve_stale")))
        adv.addWidget(self.serve_stale)
        adv.addWidget(QLabel(tr("Raw DNS override (replaces everything above):")))
        self.raw_override = QPlainTextEdit(str(dns.get("raw_override") or ""))
        self.raw_override.setPlaceholderText('{"servers": [...]}')
        self.raw_override.setLayoutDirection(Qt.LeftToRight)
        adv.addWidget(self.raw_override)
        layout.addWidget(CollapsibleSection(tr("Advanced"), adv_widget))

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_revert = QPushButton(tr("Revert"))
        self.btn_revert.clicked.connect(self.revert)
        self.btn_revert.setEnabled(False)
        self.btn_apply = QPushButton(tr("Apply"))
        self.btn_apply.clicked.connect(self.apply)
        self.btn_apply.setEnabled(False)
        bottom.addWidget(self.btn_revert)
        bottom.addWidget(self.btn_apply)
        layout.addLayout(bottom)

        self._mark_widgets_dirty()
        self._loading = False
        self._loaded = self._collect()
        self._update_buttons()
        self._set_dirty(False)

    def _mark_widgets_dirty(self) -> None:
        """Connect every field to the dirty tracker. Programmatic fills fire
        these too, but _collect() still equals _loaded then, so no signal is
        emitted unless the value genuinely differs."""
        self.servers.textChanged.connect(lambda *_: self._maybe_notify_dirty())
        self.strategy.currentIndexChanged.connect(lambda _i: self._maybe_notify_dirty())
        self.hosts.textChanged.connect(lambda *_: self._maybe_notify_dirty())
        self.domestic.textChanged.connect(lambda *_: self._maybe_notify_dirty())
        self.remote_via_tunnel.toggled.connect(lambda _c: self._maybe_notify_dirty())
        self.parallel_query.toggled.connect(lambda _c: self._maybe_notify_dirty())
        self.serve_stale.toggled.connect(lambda _c: self._maybe_notify_dirty())
        self.raw_override.textChanged.connect(lambda *_: self._maybe_notify_dirty())

    def _fill(self, servers: list[str]) -> None:
        self.servers.setPlainText("\n".join(servers))

    def _fill_domestic(self, addrs: list[str]) -> None:
        self.domestic.setText(", ".join(addrs))

    def _update_note(self) -> None:
        if self.remote_via_tunnel.isChecked():
            self.note.setText(tr(
                "DNS queries for other sites go through the tunnel; "
                "the proxy and any resolver hostname still resolve directly."))
        else:
            self.note.setText(
                tr("DNS queries leave over your normal connection, not the tunnel."))

    @staticmethod
    def _lines(widget: QPlainTextEdit) -> list[str]:
        return [ln.strip() for ln in widget.toPlainText().splitlines() if ln.strip()]

    def _domestic_entries(self) -> list[str]:
        text = self.domestic.text().strip()
        return [e for e in re.split(r"[,\s]+", text) if e]

    def _collect(self) -> dict:
        candidate = dict(self._dns)
        candidate.update(
            servers=dns_mod.clean_servers(self._lines(self.servers)),
            query_strategy=self.strategy.currentData(),
            hosts=self._lines(self.hosts),
            domestic_servers=dns_mod.clean_domestic(self._domestic_entries()),
            remote_via_tunnel=self.remote_via_tunnel.isChecked(),
            parallel_query=self.parallel_query.isChecked(),
            serve_stale=self.serve_stale.isChecked(),
            raw_override=self.raw_override.toPlainText().strip(),
        )
        return candidate

    def _maybe_notify_dirty(self) -> None:
        if self._loading:
            return
        dirty = self._collect() != self._loaded
        if dirty != self._dirty:
            self._set_dirty(dirty)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._update_buttons()
        self.dirtyChanged.emit(dirty)

    def is_dirty(self) -> bool:
        return self._dirty

    def result_dns(self) -> dict:
        """The committed DNS dict -- settings["dns"]'s shape. Returns the
        live object (like the old dialog) so a caller that snapshots it
        earlier can detect later rewrites."""
        return self._dns

    # -- load / revert -------------------------------------------------------
    def load(self, dns_cfg: dict, routing_cfg) -> None:
        """Replace the page's content and re-baseline the dirtiness. Never
        emits dirtyChanged while populating."""
        self._loading = True
        self._dns = dict(dns_cfg)
        self._routing_cfg = routing_cfg
        self.servers.setPlainText("\n".join(self._dns.get("servers") or []))
        current = str(self._dns.get("query_strategy") or "")
        self.strategy.setCurrentIndex(max(0, self.strategy.findData(current)))
        self.hosts.setPlainText("\n".join(self._dns.get("hosts") or []))
        self.domestic.setText(", ".join(self._dns.get("domestic_servers") or []))
        self.remote_via_tunnel.setChecked(bool(self._dns.get("remote_via_tunnel")))
        self.parallel_query.setChecked(bool(self._dns.get("parallel_query")))
        self.serve_stale.setChecked(bool(self._dns.get("serve_stale")))
        self.raw_override.setPlainText(str(self._dns.get("raw_override") or ""))
        self._update_note()
        self._loading = False
        self._loaded = self._collect()
        self._loaded_routing = dict(routing_cfg)
        self.status_label.clear()
        self._set_dirty(False)

    def revert(self) -> None:
        self.load(self._loaded, self._loaded_routing)

    def expand_sections(self) -> None:
        """Lower the Advanced section so a fresh sidebar view shows everything."""
        for section in self.findChildren(CollapsibleSection):
            section.set_expanded(True)

    # -- apply ---------------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_buttons()

    def _update_buttons(self) -> None:
        enable = self._dirty and not self._busy
        self.btn_apply.setEnabled(enable)
        self.btn_revert.setEnabled(enable)
        # Enter anywhere on the page triggers the default button; only keep
        # it on Apply while there is actually something to apply.
        self.btn_apply.setDefault(self._dirty)

    def apply(self) -> None:
        if self._busy:
            return
        # Xray exits on a config it cannot parse, so refuse to apply a bad
        # entry rather than let the next connect fail with nothing to explain
        # it. Each *_reasons() pair is (value, an unformatted English
        # template); tr() translates the template and fills in the value
        # itself, which stays as the user actually typed it either way.
        bad = dns_mod.invalid_server_reasons(self._lines(self.servers))
        if bad:
            self.status_label.setText("\n\n".join(
                tr(tmpl, value=_ltr(value)) for value, tmpl in bad[:8]))
            self.applyFinished.emit(False)
            return
        bad_domestic = dns_mod.validate_domestic_reasons(self._domestic_entries())
        if bad_domestic:
            self.status_label.setText("\n\n".join(
                tr(tmpl, value=_ltr(value)) for value, tmpl in bad_domestic[:8]))
            self.applyFinished.emit(False)
            return
        raw_issues = dns_mod.raw_override_issue_reasons(self.raw_override.toPlainText())
        if raw_issues:
            self.status_label.setText("\n\n".join(
                tr(tmpl, value=_ltr(value)) for value, tmpl in raw_issues[:8]))
            self.applyFinished.emit(False)
            return

        candidate = self._collect()
        self._set_busy(True)
        self.status_label.setText(tr("Validating…"))
        routing_cfg = self._routing_cfg

        def work():
            rules = routing_mod.build_rules(routing_cfg)
            strategy = routing_mod.domain_strategy_for(routing_cfg)
            # include_tun=False: `xray run -test` tries to actually open the
            # TUN device even just to validate, and fails as an unprivileged
            # user ("device or resource busy"). Routing/DNS validity doesn't
            # depend on the TUN inbound being present.
            text = render.build_text(
                _CHECK_PROFILE, "lo", routing_rules=rules, domain_strategy=strategy,
                include_tun=False, dns_cfg=candidate,
            )
            return xraycheck.check_config(text)

        def done(result=None, error=None):
            self._set_busy(False)
            if error:
                self.status_label.setText("")
                # A raw failure from the validation plumbing itself (OS/IO),
                # not a translated app message -- stays in English.
                QMessageBox.warning(self, tr("Validation failed"), str(error))
                self.applyFinished.emit(False)
                return
            if result:
                # xraycheck.check_config's own text is Xray's raw parser
                # output -- also stays in English, same as any other error
                # straight from Xray or the OS.
                self.status_label.setText(result)
                self.applyFinished.emit(False)
                return
            self.status_label.setText("")
            self._dns = candidate
            self._loading = True
            self._loaded = self._collect()
            self._loading = False
            self._set_dirty(False)
            self._set_busy(False)
            self.applied.emit(dict(candidate))
            self.applyFinished.emit(True)

        self._run_async(work, done)

    def _run_async(self, fn, done) -> None:
        worker = Worker(fn)

        def finish(result=None, error=None):
            self._workers.discard(worker)
            done(result=result, error=error)

        worker.signals.finished.connect(lambda r: finish(result=r))
        worker.signals.error.connect(lambda e: finish(error=e))
        self._workers.add(worker)
        self.pool.start(worker)
