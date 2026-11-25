"""The Security settings page.

One place for every real-IP protection: the kill switch, strict mode, the
leak check, the OS firewall, and (macOS) the password-free helper. The status
banner at the top reports only state that is actually live on this machine —
it never claims a protection that is not active.
"""
from __future__ import annotations

import sys
import types

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core import firewall as firewall_mod
from ..core import leakcheck as leakcheck_mod
from ..core import macos_helper as macos_helper_mod
from ..core import network
from ..core import strict as strict_mod
from ..i18n import ltr, tr
from .help import set_help
from .mac import InsetGroup, Switch
from .rule_editor import CollapsibleSection
from .workers import Worker


def security_summary(settings: dict, connection_state) -> list[tuple[str, str, bool]]:
    """The honest status banner.

    Returns a list of ``(label, state_text, is_real_state)``. Every value is
    read from *connection_state*, which must carry only live state (the kill
    switch blackholes, the IPv6 route table, the firewall, the last leak
    verdict) — never a setting — so the banner can never claim a protection
    that is not actually active.
    """
    items: list[tuple[str, str, bool]] = []

    ks = bool(getattr(connection_state, "killswitch_active", False))
    items.append((tr("Kill switch"), tr("Active") if ks else tr("Off"), ks))

    v6 = bool(getattr(connection_state, "ipv6_blocked", False))
    items.append((tr("IPv6"), tr("Blocked") if v6 else tr("Not blocked"), v6))

    if not getattr(connection_state, "firewall_supported", False):
        items.append((tr("OS firewall"), tr("Not supported"), False))
    else:
        fw = bool(getattr(connection_state, "firewall_active", False))
        items.append((tr("OS firewall"), tr("Active") if fw else tr("Inactive"), fw))

    lc = str(getattr(connection_state, "leakcheck_status", "") or "")
    items.append((tr("Leak check"), lc or tr("Not run"), lc == "protected"))

    return items


class SecurityPage(QWidget):
    """The Security topic: kill switch, strict mode, leak check, firewall,
    and the macOS password-free helper."""

    def __init__(self, settings: dict, parent=None, connection=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._connection = connection
        self._workers: set = set()
        self._leak_busy = False
        self._helper_busy = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(tr("Security"))
        title.setObjectName("H1")
        layout.addWidget(title)

        # Status banner: only real, live state.
        self._banner = QFrame(self)
        self._banner.setObjectName("InsetGroup")
        self._banner_layout = QVBoxLayout(self._banner)
        self._banner_layout.setContentsMargins(12, 8, 12, 8)
        self._banner_layout.setSpacing(4)
        self._banner_items: list[tuple[QFrame, QLabel]] = []
        for label, _state, _real in security_summary(self._settings, self._live_state()):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            dot = QFrame()
            dot.setFixedSize(8, 8)
            state = QLabel("")
            state.setObjectName("Muted")
            state.setWordWrap(True)
            state.setStyleSheet("background: transparent;")
            name = QLabel(label)
            name.setStyleSheet("background: transparent;")
            row.addWidget(name, 0)
            row.addStretch(1)
            row.addWidget(dot, 0)
            row.addWidget(state, 0)
            self._banner_layout.addLayout(row)
            self._banner_items.append((dot, state))
        layout.addWidget(self._banner)
        self._render_banner()

        # Kill switch (moved here from the General page).
        kill_group = InsetGroup(self)
        self.killswitch = Switch()
        self.killswitch.setChecked(
            bool((self._settings.get("killswitch") or {}).get("enabled")))
        kill_group.add_row(tr("Block the internet if the VPN drops (kill switch)"),
                           self.killswitch,
                           tr("Applies from the next connect."))
        set_help(self.killswitch,
                 tr("If the tunnel dies while you are connected, your traffic is "
                    "blocked instead of falling back to your normal connection and "
                    "leaking your real IP. Turn it off and disconnect to get your "
                    "internet back."),
                 tr("Protects an account that bans your real IP if the VPN drops."))
        layout.addWidget(kill_group)

        # Strict mode.
        strict_group = InsetGroup(self)
        strict_cfg = self._settings.get("strict") or {}
        self.strict_enabled = Switch()
        self.strict_enabled.setChecked(bool(strict_cfg.get("enabled")))
        strict_group.add_row(tr("Strict mode"), self.strict_enabled)
        set_help(self.strict_enabled,
                 tr("Sends AI sites (ChatGPT, Claude, Gemini and more) always through "
                    "the tunnel, ahead of every 'direct' rule such as Iran-direct or "
                    "your bypass lists, and resolves their names through the tunnel. "
                    "Edit the list below."),
                 tr("Keep your AI accounts from ever seeing your real IP."))

        self.strict_ai_protect = Switch()
        self.strict_ai_protect.setChecked(bool(strict_cfg.get("ai_protect", True)))
        strict_group.add_row(tr("Protect the default AI list"), self.strict_ai_protect)
        set_help(self.strict_ai_protect,
                 tr("Always include the built-in list of AI services (ChatGPT, Claude, "
                    "Gemini and more) in the protected names."),
                 tr("Turn off only if you manage the list yourself."))

        self.strict_no_direct = Switch()
        self.strict_no_direct.setChecked(bool(strict_cfg.get("no_direct")))
        strict_group.add_row(tr("No direct at all"), self.strict_no_direct,
                             tr("No-direct mode routes every site through the tunnel, "
                                "including Iranian sites. Iranian sites will be slower "
                                "and some may be blocked."))
        set_help(self.strict_no_direct,
                 tr("Turns every 'direct' rule off so nothing can leave with your real "
                    "IP. Iranian sites become slower or may not open."),
                 tr("The strongest strict setting — use it only when you need it."))

        self.strict_domains = QPlainTextEdit()
        self.strict_domains.setPlaceholderText(tr("Your own names, one per line"))
        domains = strict_cfg.get("domains") or []
        if domains:
            self.strict_domains.setPlainText("\n".join(domains))
        self.strict_domains.setFixedHeight(96)
        self.strict_domains.setLayoutDirection(Qt.LeftToRight)
        reset_btn = QPushButton(tr("Reset"))
        reset_btn.clicked.connect(self._reset_domains)
        domains_row = QWidget()
        dr = QHBoxLayout(domains_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.setSpacing(8)
        dr.addWidget(self.strict_domains, 1)
        dr.addWidget(reset_btn, 0, Qt.AlignTop)
        strict_group.add_row(tr("Extra protected domains (one per line)"), domains_row)
        # Its own full-width row. add_row pins a trailing widget to its natural
        # width, and a list this long made the whole page wider than the window.
        sep = QFrame(strict_group)
        sep.setObjectName("InsetGroupSeparator")
        sep.setFixedHeight(1)
        strict_group._rows.addWidget(sep)
        builtin_row = QWidget(strict_group)
        builtin_row.setObjectName("InsetGroupRow")
        br = QVBoxLayout(builtin_row)
        br.setContentsMargins(12, 8, 12, 8)
        br.setSpacing(2)
        builtin_title = QLabel(tr("Always protected (built-in AI list)"))
        builtin_title.setObjectName("GroupRowLabel")
        builtin = QLabel(", ".join(strict_mod.DEFAULT_AI_DOMAINS))
        builtin.setObjectName("GroupRowFootnote")
        builtin.setWordWrap(True)
        builtin.setLayoutDirection(Qt.LeftToRight)
        builtin.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        builtin.setMinimumWidth(0)
        br.addWidget(builtin_title)
        br.addWidget(builtin)
        strict_group._rows.addWidget(builtin_row)
        set_help(self.strict_domains,
                 tr("Your own names to always send through the tunnel, one per line. "
                    "The default AI list is shown when this is empty."),
                 tr("Add a service the built-in list does not cover yet."))
        set_help(reset_btn,
                 tr("Clears your extra list so only the default AI list is protected."),
                 tr("Back to the built-in list."))
        layout.addWidget(strict_group)

        # Leak check.
        leak_group = InsetGroup(self)
        leak_cfg = self._settings.get("leakcheck") or {}
        self.leak_enabled = Switch()
        self.leak_enabled.setChecked(bool(leak_cfg.get("enabled")))
        leak_group.add_row(tr("Leak check"), self.leak_enabled)
        set_help(self.leak_enabled,
                 tr("After connecting, checks that the exit really is the tunnel and "
                    "warns if it is Iran or your real IP. Your full IP is never saved "
                    "or shown, only a masked form."),
                 tr("Catches a tunnel that quietly stops working."))

        self.leak_notify = Switch()
        self.leak_notify.setChecked(bool(leak_cfg.get("notify", True)))
        leak_group.add_row(tr("Notify me of a finding"), self.leak_notify)
        set_help(self.leak_notify,
                 tr("Also sends an OS notification when the leak check finds a "
                    "problem, on top of the in-app status."),
                 tr("Get pinged the moment something leaks."))

        self.btn_leak_now = QPushButton(tr("Run check now"))
        self.btn_leak_now.clicked.connect(self._run_leak_check)
        set_help(self.btn_leak_now,
                 tr("Runs the leak check right now and shows the result here."),
                 tr("Want to be sure before you trust a new server?"))
        self.leak_status = QLabel("")
        self.leak_status.setObjectName("Muted")
        self.leak_status.setWordWrap(True)
        leak_row = QWidget()
        lr = QHBoxLayout(leak_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.setSpacing(8)
        lr.addWidget(self.leak_status, 1)
        lr.addWidget(self.btn_leak_now, 0)
        leak_group.add_row(tr("Check the tunnel exit"), leak_row)
        layout.addWidget(leak_group)

        # OS firewall (advanced, collapsed; hidden entirely when unsupported).
        # supported() shells out to find the firewall tool; a failure (or a
        # platform we do not run on) means "not supported", never a crash.
        try:
            self._firewall_supported = bool(firewall_mod.supported())
        except Exception:
            self._firewall_supported = False
        if self._firewall_supported:
            fw_cfg = self._settings.get("firewall") or {}
            fw_content = InsetGroup(self)
            self.firewall_enabled = Switch()
            self.firewall_enabled.setChecked(bool(fw_cfg.get("enabled")))
            fw_content.add_row(tr("OS firewall lockdown"), self.firewall_enabled)
            set_help(self.firewall_enabled,
                     tr("The system itself drops anything outside the tunnel, even if "
                        "the app crashes or Xray dies. Strongest, but if something goes "
                        "wrong you can lose internet until you restart the app. "
                        "Protection while the app is closed lasts only until the next "
                        "launch."),
                     tr("The strongest layer — and the one that can cut you off."))

            self.firewall_allow_lan = Switch()
            self.firewall_allow_lan.setChecked(bool(fw_cfg.get("allow_lan", True)))
            fw_content.add_row(tr("Allow the local network"), self.firewall_allow_lan)
            set_help(self.firewall_allow_lan,
                     tr("Lets traffic to your own LAN and link-local addresses through "
                        "the lockdown, so printers and home devices keep working."),
                     tr("Keep it on unless you have a reason to block the LAN."))

            self._firewall_section = CollapsibleSection(tr("Advanced"), fw_content)
            set_help(self._firewall_section.toggle,
                     tr("The OS firewall lockdown, the strongest layer. It is off by "
                        "default because it can cut your internet if something goes "
                        "wrong."),
                     tr("Expand to turn it on."))
            layout.addWidget(self._firewall_section)
        else:
            self._firewall_section = None
            self.firewall_enabled = None
            self.firewall_allow_lan = None

        # macOS password-free helper.
        if self._macos_helper_applicable():
            helper_group = InsetGroup(self)
            self.btn_helper = QPushButton("")
            self.btn_helper.clicked.connect(self._toggle_helper)
            self.helper_status = QLabel("")
            self.helper_status.setObjectName("Muted")
            self.helper_status.setWordWrap(True)
            helper_row = QWidget()
            hr = QHBoxLayout(helper_row)
            hr.setContentsMargins(0, 0, 0, 0)
            hr.setSpacing(8)
            hr.addWidget(self.helper_status, 1)
            hr.addWidget(self.btn_helper, 0)
            helper_group.add_row(tr("Password-free start"), helper_row)
            set_help(self.btn_helper,
                     tr("Installs a small background helper once (one password) so the "
                        "app opens without asking again. Uninstall any time here."),
                     tr("Stop being asked for your password on every launch."))
            layout.addWidget(helper_group)
            self._sync_helper_button()
        else:
            self.btn_helper = None

        # Always-visible honesty: what these layers do not cover.
        self._not_covered = QLabel(tr(
            "What this does not cover: Serverless-only mode always uses your real IP; "
            "nothing is protected before you connect or after you disconnect; apps "
            "with their own tunnels are out of scope."))
        self._not_covered.setObjectName("Muted")
        self._not_covered.setWordWrap(True)
        layout.addWidget(self._not_covered)

        layout.addStretch(1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_banner_timer", None) is None:
            self._banner_timer = QTimer(self)
            self._banner_timer.timeout.connect(self._render_banner)
        self._render_banner()
        self._banner_timer.start(3000)

    def hideEvent(self, event) -> None:
        timer = getattr(self, "_banner_timer", None)
        if timer is not None:
            timer.stop()
        super().hideEvent(event)

    # -- status banner ------------------------------------------------------
    def _live_state(self) -> types.SimpleNamespace:
        """Read the live protection state. Every read is guarded: a failure
        must degrade to "not active", never to a false claim of protection."""
        st = types.SimpleNamespace()
        conn = self._connection
        st.killswitch_active = bool(getattr(conn, "killswitch_active", False)) if conn else False
        try:
            st.ipv6_blocked = bool(network.ipv6_blocked())
        except Exception:
            st.ipv6_blocked = False
        try:
            st.firewall_supported = bool(firewall_mod.supported())
            st.firewall_active = (firewall_mod.status() == "active")
        except Exception:
            st.firewall_supported = False
            st.firewall_active = False
        # The settings window has no live leak verdict of its own, so it never
        # claims the tunnel is verified — it only reports "not run".
        st.leakcheck_status = ""
        return st

    def _render_banner(self) -> None:
        for (dot, state), (_label, state_text, real) in zip(
                self._banner_items,
                security_summary(self._settings, self._live_state()), strict=True):
            state.setText(state_text)
            dot.setStyleSheet(
                f"background:{'#30d158' if real else '#8e8e93'}; border-radius:4px;")

    # -- domains ------------------------------------------------------------
    def _reset_domains(self) -> None:
        self.strict_domains.setPlainText("")

    # -- leak check ---------------------------------------------------------
    def _run_leak_check(self) -> None:
        if self._leak_busy:
            return
        conn = self._connection
        if conn is None or not getattr(conn, "is_connected", lambda: False)():
            self.leak_status.setText(tr("Connect first to run the leak check."))
            return
        alias = getattr(getattr(conn, "state", None), "alias", None)
        if not alias:
            self.leak_status.setText(tr("Connect first to run the leak check."))
            return
        self._leak_busy = True
        self.btn_leak_now.setEnabled(False)
        self.leak_status.setText(tr("Checking…"))
        cache = leakcheck_mod.RealIpCache()

        def work():
            return leakcheck_mod.run_check(None, alias, cache)

        def done(result=None, error=None):
            self._leak_busy = False
            self.btn_leak_now.setEnabled(True)
            if error or result is None:
                self.leak_status.setText(tr("Could not verify the tunnel exit."))
                return
            text = tr(leakcheck_mod.message(result))
            if result.real_ip_masked:
                text += f"  ({ltr(result.real_ip_masked)})"
            self.leak_status.setText(text)

        self._run_async(work, done)

    # -- macOS helper -------------------------------------------------------
    def _macos_helper_applicable(self) -> bool:
        return (sys.platform == "darwin"
                and macos_helper_mod._is_mac()
                and macos_helper_mod.installed())

    def _sync_helper_button(self) -> None:
        if self.btn_helper is None:
            return
        if macos_helper_mod.installed():
            self.btn_helper.setText(tr("Uninstall helper"))
        else:
            self.btn_helper.setText(tr("Install helper"))

    def _toggle_helper(self) -> None:
        if self._helper_busy or self.btn_helper is None:
            return
        self._helper_busy = True
        self.btn_helper.setEnabled(False)
        installing = not macos_helper_mod.installed()
        fn = macos_helper_mod.install if installing else macos_helper_mod.uninstall

        def done(result=None, error=None):
            self._helper_busy = False
            if self.btn_helper is not None:
                self.btn_helper.setEnabled(True)
                self._sync_helper_button()
            if error:
                self.helper_status.setText(str(error))
                return
            if installing:
                self.helper_status.setText(
                    tr("Password-free start is on: sushTun will open without asking "
                       "for the password.") if result
                    else tr("Could not install the password-free helper."))
            else:
                self.helper_status.setText(
                    tr("Helper removed.") if result
                    else tr("Could not remove the helper."))

        self._run_async(fn, done)

    # -- async helper (same pattern as the other pages) ---------------------
    def _run_async(self, fn, done) -> None:
        worker = Worker(fn)

        def finish(result=None, error=None):
            try:
                self._workers.discard(worker)
                done(result=result, error=error)
            except RuntimeError:
                pass  # the window died between start and delivery

        worker.signals.finished.connect(lambda r: finish(result=r))
        worker.signals.error.connect(lambda e: finish(error=e))
        self._workers.add(worker)
        QThreadPool.globalInstance().start(worker)

    # -- collect / apply ----------------------------------------------------
    def collect(self) -> dict:
        domains = [ln.strip() for ln in self.strict_domains.toPlainText().splitlines()
                   if ln.strip()]
        out: dict = {
            "killswitch": {"enabled": self.killswitch.isChecked()},
            "strict": {
                "enabled": self.strict_enabled.isChecked(),
                "ai_protect": self.strict_ai_protect.isChecked(),
                "no_direct": self.strict_no_direct.isChecked(),
                "domains": strict_mod.sanitize_domains(domains),
            },
            "leakcheck": {
                **self._settings.get("leakcheck", {}),
                "enabled": self.leak_enabled.isChecked(),
                "notify": self.leak_notify.isChecked(),
            },
        }
        if self.firewall_enabled is not None:
            out["firewall"] = {
                "enabled": self.firewall_enabled.isChecked(),
                "allow_lan": self.firewall_allow_lan.isChecked(),
            }
        return out

    def apply_to(self, target: dict) -> None:
        target.update(self.collect())
