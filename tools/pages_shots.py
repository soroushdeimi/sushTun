"""Render the embeddable Routing and DNS pages en and fa for the worker's
screenshots, at the sidebar content widths used by the dining-area dialogs
(576 and 796). Offscreen; one Grab per page state, dirtied with a change."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_FONT_DPI", "120")

from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from xrayui.core.settings import DEFAULTS
from xrayui.i18n import set_language
from xrayui.ui import theme
from xrayui.ui.pages.dns_page import DnsPage
from xrayui.ui.pages.routing_page import RoutingPage
from xrayui.ui.rule_editor import CollapsibleSection

_FA_FONTS = '"Vazirmatn", "Noto Sans Arabic", "Segoe UI", "Tahoma", "Geeza Pro"'
_WIDTHS = (576, 796)

app = QApplication([])


def build_and_grab(lang, out):
    set_language(lang)
    app.setStyleSheet(theme.build_stylesheet(f"{_FA_FONTS}, {theme._FONT}"))

    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)

    routing = RoutingPage(DEFAULTS["routing"])
    routing.domains.setPlainText("example.com\ngeosite:iran")
    routing._add_set("empty")
    lay.addWidget(routing)
    dns = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    dns.servers.setPlainText("1.1.1.1\n8.8.8.8")
    dns._fill_domestic(["178.22.122.100", "185.51.200.2"])
    dns.remote_via_tunnel.setChecked(True)
    for page in (routing, dns):
        for section in page.findChildren(CollapsibleSection):
            section.set_expanded(True)
    lay.addWidget(dns)
    host.show()

    for width in _WIDTHS:
        routing.setFixedWidth(width)
        dns.setFixedWidth(width)
        app.processEvents()
        routing.grab().save(os.path.join(out, f"routing_{lang}_{width}.png"))
        dns.grab().save(os.path.join(out, f"dns_{lang}_{width}.png"))

    host.close()


out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".worker")
out = os.path.abspath(out)
os.makedirs(out, exist_ok=True)
build_and_grab("en", out)
build_and_grab("fa", out)
print("saved under", out)
