"""Renders the README screenshots offscreen from fictional data.

Everything shown is built in a temporary directory (documentation address
ranges and example.com hosts); no real profile or system state is read. The
stubs are the ones tools/ui_tour.py uses, so nothing touches the network.

Run:
    QT_QPA_PLATFORM=offscreen .venv/bin/python tools/readme_shots.py [out_dir]

Writes servers.png, chains.png, routing.png and anti-filter.png (default
out_dir: docs/screenshots).
"""
from __future__ import annotations

import copy
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_SCALE_FACTOR"] = "1.5"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ui_tour  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

WINDOW = (1100, 720)
CHAINS_HEIGHT = 790
ROUTING_HEIGHT = 940
SETTINGS_HEIGHT = 820
PNG_QUALITY = 20

# name, protocol, address, port, exit country, delay ms
SERVERS = [
    ("Frankfurt", "vless", "203.0.113.10", "DE", 48),
    ("Amsterdam", "trojan", "203.0.113.24", "NL", 63),
    ("Helsinki", "vless", "198.51.100.17", "FI", 91),
    ("London", "hysteria2", "198.51.100.42", "GB", 74),
    ("Tokyo", "vmess", "203.0.113.77", "JP", 212),
    ("Tehran", "vless", "198.51.100.5", "IR", 29),
]


def _seed(base_dir: Path) -> None:
    from xrayui import paths
    from xrayui.core import chain_test, chains
    from xrayui.core import settings as app_settings
    from xrayui.core.profiles import Profile, ProfileStore
    from xrayui.core.speedtest import ResultStore
    from xrayui.core.subscription import Subscription, SubscriptionStore, Usage

    paths.base_dir = lambda: base_dir
    paths.state_dir = lambda: base_dir / "state"
    paths.profiles_dir = lambda: base_dir / "profiles"
    paths.ensure_dirs()

    settings = copy.deepcopy(app_settings.DEFAULTS)
    settings["language"] = "en"
    settings["tour_seen"] = True
    routing = settings["routing"]
    routing.update(block_ads=True, direct_iran=True, direct_private=True,
                   bypass_domains=["intranet.example.com", "bank.example.ir", "shop.example.ir",
                                   "news.example.ir", "geosite:ir"],
                   bypass_ips=["198.51.100.0/24", "203.0.113.128/25", "geoip:ir"],
                   proxy_domains=["video.example.com", "chat.example.org", "docs.example.net"])
    core = settings["core"]
    core["fragment"].update(enabled=True, packets="tlshello", length="100-200",
                            interval="10-20")
    core["mux"].update(enabled=True, concurrency=8, xudp_concurrency=16)
    core["udp_noise"].update(enabled=True, length="10-20", delay="10-16")
    app_settings.save(settings)

    store = ProfileStore()
    results = ResultStore()
    saved = {}
    for index, (name, protocol, address, country, delay) in enumerate(SERVERS):
        kwargs = dict(name=name, protocol=protocol, address=address, port=443,
                      id=f"00000000-0000-4000-8000-{index:012d}")
        if protocol == "vless":
            kwargs.update(network="tcp", security="reality", sni="www.example.com",
                          fp="chrome", pbk="A" * 43, sid="ab")
        elif protocol == "trojan":
            kwargs.update(network="tcp", security="tls", sni="nl.example.com")
        elif protocol == "vmess":
            kwargs.update(network="grpc", security="tls", sni="jp.example.com",
                          service_name="svc", vmess_security="auto")
        else:
            kwargs.update(hy2_obfs_password="example", hy2_ports="20000-30000")
        saved[name] = store.save(Profile(**kwargs))
        results.set(saved[name].uid, delay_ms=float(delay), error=None, skipped=False,
                    country=country, exit_ip=f"203.0.113.{10 + index}")
    store.set_active(saved["Frankfurt"].uid)

    subs = SubscriptionStore()
    subs.save(Subscription(
        name="Main plan", url="https://sub.example.com/main", enabled=True,
        usage=Usage(upload=2_000_000_000, download=31_000_000_000,
                    total=100_000_000_000, expire=0),
        updated=time.time(),
        profile_uids=[saved[name].uid for name in ("Frankfurt", "Amsterdam", "Helsinki")],
    ))

    chain_store = chains.ChainStore()
    good = chain_store.save(chains.Chain(
        name="Relay to Frankfurt",
        hops=[saved["Tehran"].uid, saved["Helsinki"].uid, saved["Frankfurt"].uid]))
    bad = chain_store.save(chains.Chain(
        name="Relay to Amsterdam",
        hops=[saved["Tehran"].uid, saved["Tokyo"].uid, saved["Amsterdam"].uid]))
    reports = chain_test.ResultStore()
    now = time.time()
    reports.set(good.uid, verdict="OK", broken_at=None, country="DE",
                exit_ip="203.0.113.10", warm_ms=118.0, cold_ms=164.0, download_mbps=46.0,
                timestamp=now - 120,
                prefixes=[dict(latency_ms=29.0, country="IR"),
                          dict(latency_ms=71.0, country="FI"),
                          dict(latency_ms=118.0, country="DE")])
    reports.set(bad.uid, verdict="BROKEN_AT", broken_at=2, country="", exit_ip="",
                warm_ms=None, cold_ms=None, download_mbps=None, timestamp=now - 300,
                prefixes=[dict(latency_ms=29.0, country="IR"),
                          dict(error="timeout")])


def _save(widget, path: Path) -> None:
    QApplication.instance().processEvents()
    pixmap = widget.grab()
    pixmap.save(str(path), "PNG", PNG_QUALITY)
    print(f"{path}  {pixmap.width()}x{pixmap.height()}  {path.stat().st_size // 1024} KB")


def _connect(win) -> None:
    profile = win.store.get(win.store.active_uid())
    win.conn._connected = True
    win.conn.state.profile_uid = profile.uid
    win.conn.state.chain_uid = ""
    win.conn.state.alias = "Ethernet"
    win.conn.state.ipv4 = "192.0.2.15"
    win.conn.state.gateway = "192.0.2.1"
    win.conn.state.tun_index = None
    win.conn.xray.is_running = lambda: True
    win._connected_chain = None
    win._refresh_status()


def render(out_dir: Path) -> None:
    from xrayui import i18n
    from xrayui.ui import main_window as mw
    from xrayui.ui import theme

    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    ui_tour.install_stubs()
    base_dir = Path(tempfile.mkdtemp(prefix="readme_shots_"))
    try:
        _seed(base_dir)
        i18n.set_language("en")
        app.setStyleSheet(theme.STYLESHEET)

        win = mw.MainWindow(elevated=True)
        win.resize(*WINDOW)
        win.show()
        app.processEvents()
        win.alert_banner.setVisible(False)
        _connect(win)
        win.status_card.set("throughput", "↓ 42 Mbit/s")
        win.status_card.set("used", "2.1 GB")
        win.status_card.set_timer("42:10")
        win._show_page(mw.PAGE_SERVERS)
        _save(win, out_dir / "servers.png")

        win.resize(WINDOW[0], CHAINS_HEIGHT)
        win._show_page(mw.PAGE_CHAINS)
        _save(win, out_dir / "chains.png")

        win.resize(WINDOW[0], ROUTING_HEIGHT)
        win._show_page(mw.PAGE_ROUTING)
        _save(win, out_dir / "routing.png")

        from xrayui.ui.settings_window import SettingsWindow
        dlg = SettingsWindow(win.settings, win)
        dlg.resize(WINDOW[0], SETTINGS_HEIGHT)
        dlg.show()
        dlg._select_topic("anti-filter")
        _save(dlg, out_dir / "anti-filter.png")
        dlg.close()

        win.tailer.stop()
        win.close()
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
    render(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
