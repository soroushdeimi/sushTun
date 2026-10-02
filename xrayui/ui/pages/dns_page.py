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

from ...core import dns as dns_mod
from ...core import render, xraycheck
from ...core import routing as routing_mod
from ...core.profiles import Profile
from ...i18n import ltr, tr
from ..help import set_help
from ..rule_editor import CollapsibleSection
from ..workers import Worker
from .flow import FlowLayout

_CHECK_PROFILE = Profile(
    name="dns check", protocol="vless", address="203.0.113.1", port=443,
    id="11111111-1111-1111-1111-111111111111", encryption="none",
    network="tcp", security="none",
)


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

        presets = FlowLayout()
        presets_label = QLabel(tr("Preset:"))
        presets_label.setWordWrap(True)
        presets.addWidget(presets_label)
        for name, servers in dns_mod.PRESETS.items():
            btn = QPushButton(name)
            btn.clicked.connect(lambda _=False, s=servers: self._fill(s))
            set_help(btn,
                     tr("Fills the list below with {name}'s servers. You still need "
                        "to press Apply.", name=name),
                     tr("No idea which DNS to trust? Start with a well-known one."))
            presets.addWidget(btn)
        layout.addLayout(presets)

        resolver_label = QLabel(tr("Resolvers (one per line, in order):"))
        resolver_label.setWordWrap(True)
        layout.addWidget(resolver_label)
        self.servers = QPlainTextEdit("\n".join(dns.get("servers") or []))
        self.servers.setPlaceholderText(
            tr("Leave empty to keep the template's servers.") + "\n"
            "https://1.1.1.1/dns-query\n"
            "tcp://9.9.9.9:53\n"
            "8.8.8.8\n"
            + tr("Use literal IPs — a hostname needs another resolver to look it up first.")
        )
        self.servers.setLayoutDirection(Qt.LeftToRight)
        resolver_help = (
            tr("The DNS servers that turn website names into addresses, tried in "
               "order. Leave it empty to keep the built-in ones."),
            tr("Put your favourite first and a backup on the next line."))
        set_help(self.servers, *resolver_help)
        set_help(resolver_label, *resolver_help)
        layout.addWidget(self.servers, 2)

        strategy = QHBoxLayout()
        strategy.addWidget(QLabel(tr("Query strategy:")))
        self.strategy = QComboBox()
        self.strategy.addItem(tr("Template default"), "")
        for name in dns_mod.QUERY_STRATEGIES:
            self.strategy.addItem(name, name)
        current = str(dns.get("query_strategy") or "")
        self.strategy.setCurrentIndex(max(0, self.strategy.findData(current)))
        strategy_label = strategy.itemAt(0).widget()
        strategy_help = (
            tr("Which kinds of address to ask for. UseIPv4 is the safe pick here, "
               "because the tunnel can't carry IPv6 and an IPv6 answer would "
               "bypass it."),
            tr("Sites load on some pages and not others? Try UseIPv4."))
        set_help(self.strategy, *strategy_help)
        set_help(strategy_label, *strategy_help)
        strategy.addWidget(self.strategy, 1)
        layout.addLayout(strategy)

        over_label = QLabel(tr("Static overrides (domain = address):"))
        over_label.setWordWrap(True)
        layout.addWidget(over_label)
        self.hosts = QPlainTextEdit("\n".join(dns.get("hosts") or []))
        self.hosts.setPlaceholderText(
            "example.com = 93.184.216.34\ncdn.example.com = 1.2.3.4, 5.6.7.8")
        self.hosts.setLayoutDirection(Qt.LeftToRight)
        hosts_help = (
            tr("Fixed answers for names you choose, one per line, written as "
               "name = address. They win over any DNS server."),
            tr("Point your home server's name straight at its address."))
        set_help(self.hosts, *hosts_help)
        set_help(over_label, *hosts_help)
        layout.addWidget(self.hosts, 1)

        # -- Domestic DNS ----------------------------------------------
        dom_label = QLabel(tr("Domestic DNS (for sites that go direct):"))
        domestic_help = (
            tr("DNS servers used only for sites your routing sends direct, so local "
               "sites resolve to local addresses."),
            tr("Your country's sites open faster when a local DNS answers for them."))
        set_help(dom_label, *domestic_help)
        dom_label.setWordWrap(True)
        layout.addWidget(dom_label)
        self.domestic = QLineEdit(", ".join(dns.get("domestic_servers") or []))
        self.domestic.setPlaceholderText("178.22.122.100, 185.51.200.2")
        set_help(self.domestic, *domestic_help)
        self.domestic.setLayoutDirection(Qt.LeftToRight)
        layout.addWidget(self.domestic)
        dom_row = FlowLayout()
        for name, addrs in dns_mod.DOMESTIC_PRESETS.items():
            btn = QPushButton(name)
            btn.clicked.connect(lambda _=False, a=addrs: self._fill_domestic(a))
            set_help(btn,
                     tr("Fills the domestic DNS with {name}'s addresses. You still "
                        "need to press Apply.", name=name),
                     tr("A well-known DNS service for sites inside Iran."))
            dom_row.addWidget(btn)
        off_btn = QPushButton(tr("Off"))
        off_btn.clicked.connect(lambda: self._fill_domestic([]))
        set_help(off_btn,
                 tr("Clears the domestic DNS, so direct sites use the main list above."),
                 tr("Switch it off if a local DNS gives you wrong answers."))
        dom_row.addWidget(off_btn)
        layout.addLayout(dom_row)

        # -- Remote via tunnel -------------------------------------------
        self.remote_via_tunnel = QCheckBox(tr("Resolve other sites through the tunnel"))
        set_help(self.remote_via_tunnel,
                 tr("Sends the DNS questions for sites that use the tunnel through "
                    "the tunnel too, so your provider can't see or alter them."),
                 tr("Your ISP redirects blocked sites to a warning page? This stops that."))
        self.remote_via_tunnel.setChecked(bool(dns.get("remote_via_tunnel")))
        self.remote_via_tunnel.toggled.connect(self._update_note)
        layout.addWidget(self.remote_via_tunnel)

        self.note = QLabel()
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self._update_note()

        # -- Advanced ---------------------------------------------------
        adv_widget = QWidget()
        adv = QVBoxLayout(adv_widget)
        adv.setContentsMargins(0, 4, 0, 0)
        self.parallel_query = QCheckBox(tr("Parallel query"))
        self.parallel_query.setChecked(bool(dns.get("parallel_query")))
        set_help(self.parallel_query,
                 tr("Asks all the DNS servers at once and takes the first answer, "
                    "instead of one after another."),
                 tr("A slow first server stops holding up every page."))
        adv.addWidget(self.parallel_query)
        self.serve_stale = QCheckBox(tr("Serve stale"))
        self.serve_stale.setChecked(bool(dns.get("serve_stale")))
        set_help(self.serve_stale,
                 tr("Lets Xray reuse a recently expired answer while it fetches a "
                    "fresh one in the background."),
                 tr("Pages start instantly even when the DNS server is slow today."))
        adv.addWidget(self.serve_stale)
        raw_label = QLabel(tr("Raw DNS override (replaces everything above):"))
        raw_label.setWordWrap(True)
        adv.addWidget(raw_label)
        self.raw_override = QPlainTextEdit(str(dns.get("raw_override") or ""))
        self.raw_override.setPlaceholderText('{"servers": [...]}')
        self.raw_override.setLayoutDirection(Qt.LeftToRight)
        raw_help = (
            tr("Your own Xray DNS configuration in JSON. When filled in, it "
               "replaces every other DNS setting on this page."),
            tr("For experts: paste a config someone else tested."))
        set_help(self.raw_override, *raw_help)
        set_help(raw_label, *raw_help)
        adv.addWidget(self.raw_override)
        adv_section = CollapsibleSection(tr("Advanced"), adv_widget)
        set_help(adv_section.toggle,
                 tr("Shows the rarely needed DNS options."),
                 tr("Skip it until a guide tells you otherwise."))
        layout.addWidget(adv_section)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_revert = QPushButton(tr("Revert"))
        self.btn_revert.clicked.connect(self.revert)
        self.btn_revert.setEnabled(False)
        set_help(self.btn_revert,
                 tr("Throws away your unsaved edits and goes back to the saved DNS "
                    "settings."),
                 tr("Typed something odd? Revert and start clean."))
        self.btn_apply = QPushButton(tr("Apply"))
        self.btn_apply.clicked.connect(self.apply)
        self.btn_apply.setEnabled(False)
        set_help(self.btn_apply,
                 tr("Checks and saves your DNS settings. If you are connected, "
                    "reconnect afterwards to use them."),
                 tr("Nothing changes until you press this."))
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
                tr(tmpl, value=ltr(value)) for value, tmpl in bad[:8]))
            self.applyFinished.emit(False)
            return
        bad_domestic = dns_mod.validate_domestic_reasons(self._domestic_entries())
        if bad_domestic:
            self.status_label.setText("\n\n".join(
                tr(tmpl, value=ltr(value)) for value, tmpl in bad_domestic[:8]))
            self.applyFinished.emit(False)
            return
        raw_issues = dns_mod.raw_override_issue_reasons(self.raw_override.toPlainText())
        if raw_issues:
            self.status_label.setText("\n\n".join(
                tr(tmpl, value=ltr(value)) for value, tmpl in raw_issues[:8]))
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
