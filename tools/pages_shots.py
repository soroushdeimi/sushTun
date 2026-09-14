"""Render the embeddable Routing and DNS pages en and fa for the worker's
screenshots. Offscreen; one Grab per page state, dirtied with a change."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_FONT_DPI", "120")

from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from xrayui.core.settings import DEFAULTS
from xrayui.i18n import set_language
from xrayui.ui import theme
from xrayui.ui.dns_page import DnsPage
from xrayui.ui.routing_page import RoutingPage

_FA_FONTS = '"Vazirmatn", "Noto Sans Arabic", "Segoe UI", "Tahoma", "Geeza Pro"'

app = QApplication([])


def build_and_grab(lang, out):
    set_language(lang)
    app.setStyleSheet(theme.build_stylesheet(f"{_FA_FONTS}, {theme._FONT}"))

    host = QWidget()
    host.resize(760, 620)
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)

    routing = RoutingPage(DEFAULTS["routing"])
    routing.setMinimumWidth(430)
    routing.domains.setPlainText("example.com\ngeosite:iran")
    routing._add_set("empty")
    lay.addWidget(routing)
    host.show()
    app.processEvents()
    routing.grab().save(os.path.join(out, f"routing_{lang}.png"))

    dns = DnsPage(DEFAULTS["dns"], DEFAULTS["routing"])
    dns.setMinimumWidth(300)
    dns.servers.setPlainText("1.1.1.1\n8.8.8.8")
    lay.addWidget(dns)
    app.processEvents()
    dns.grab().save(os.path.join(out, f"dns_{lang}.png"))

    host.close()


out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".worker")
out = os.path.abspath(out)
os.makedirs(out, exist_ok=True)
build_and_grab("en", out)
build_and_grab("fa", out)
print("saved under", out)