"""Connect / disconnect orchestrator. Owns cleanup and guarantees restore."""
from __future__ import annotations

import atexit
import secrets
import socket
import sys
import time
from collections.abc import Callable

from .. import paths
from . import bootrestore, coreopts, hotspot, network, render, routing
from . import exits as exits_mod
from . import forwards as forwards_mod
from . import settings as app_settings
from . import tun2socks as t2s
from . import xray as xray_mod
from .profiles import Profile, ProfileStore
from .state import State, WgState

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = coreopts.DEFAULT_SOCKS_PORT


class ConnectError(Exception):
    pass


def _resolve(host: str) -> str:
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        return socket.gethostbyname(host)


def _wait_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect((host, port))
            return True
        except OSError:
            time.sleep(0.5)
        finally:
            s.close()
    return False


def _hotspot_credentials() -> tuple[str, str]:
    """The Linux hotspot's name and password; the password is made once and
    kept, so phones that joined before rejoin without asking."""
    settings = app_settings.load()
    gw = settings["gateway"]
    if len(gw.get("password") or "") < 8:  # WPA2 needs 8-63 characters
        gw["password"] = secrets.token_urlsafe(9)  # 12 characters
        app_settings.save(settings)
    return gw.get("ssid") or "sushTun", gw["password"]


def _last_log_line() -> str:
    try:
        lines = paths.log_file().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "no log output"
    lines = [ln for ln in lines if ln.strip()]
    return lines[-1].strip() if lines else "no log output"


class Connection:
    def __init__(self, on_step: Callable[[str], None] | None = None) -> None:
        self._log = on_step or (lambda _m: None)
        self.state = State()
        self.xray = xray_mod.XrayProcess()
        self.tun2socks = t2s.Tun2socks()
        self._owned = False  # did this process establish the active connection?
        self._gateway_on = False
        self._dns_warned = False
        atexit.register(self._atexit)

    def is_connected(self) -> bool:
        return self.state.is_connected()

    def connect(self, profile: Profile) -> None:
        if not profile.address or not profile.id:
            raise ConnectError("profile is missing address or id")
        if profile.protocol == "wireguard" and not profile.pbk:
            raise ConnectError("WireGuard profile is missing the peer public key")
        if self.state.is_connected():
            raise ConnectError("already connected")
        wg_state = WgState()
        if wg_state.is_connected() and any(
            r in ("0.0.0.0/0", "::/0") for r in wg_state.routes()
        ):
            raise ConnectError(
                "The WireGuard lane is running a full-tunnel profile, which would fight "
                "this lane's default route. Disconnect the WireGuard lane first."
            )

        if sys.platform == "linux":
            self._log("Experimental platform (Linux) — network backend is unverified.")
        self._log("Detecting active interface...")
        iface = network.detect_interface()
        if iface is None:
            raise ConnectError("no active internet interface found")
        self._log(f"Interface {iface.alias} ({iface.ipv4}) via {iface.gateway}")
        other = network.foreign_tunnel(iface.alias)
        if other:
            raise ConnectError(
                f"another VPN is already routing traffic through {other} — "
                "disconnect it first; two full tunnels cannot share the default route"
            )

        server_ip = _resolve(profile.address)
        self._log("Backing up DNS...")
        dns = network.backup_dns(iface.alias)

        if IS_MAC:
            self._connect_macos(profile, iface, server_ip, dns)
        else:
            self._connect_generic(profile, iface, server_ip, dns)

    def _fail_connect(self, server_ip: str, reason: str) -> None:
        """Tear down a half-built connection, then report why it failed."""
        self.tun2socks.stop()
        self.xray.stop()
        network.remove_routes(server_ip)
        paths.runtime_config().unlink(missing_ok=True)
        raise ConnectError(reason)

    def _exits(self, cfgs: dict) -> list[exits_mod.Exit]:
        # A bad or busy multi-exit setting is dropped here with a warning;
        # it must never keep the main connection from starting.
        exits, warning = exits_mod.prepare(cfgs.get("exits"), cfgs.get("core"),
                                           ProfileStore().get)
        if warning:
            self._log(f"WARNING: {warning}")
        return exits

    def _retry_without_extras(self, build, exits, forwards) -> None:
        """Start again without the multi-exit port and the port forwards when
        one of their ports turned out to be taken.

        Their ports are checked before connecting, but another program can take
        one in between, and Xray then refuses to start -- which would take the
        whole tunnel down for an optional feature.
        """
        if not exits and not forwards:
            return
        deadline = time.time() + 1.5
        while time.time() < deadline:
            if not self.xray.is_running():
                if "address already in use" not in _last_log_line().lower():
                    return  # a different startup failure: leave it to the caller
                self._log("WARNING: a port of the multi-exit port or of a port forward is "
                          "in use; starting without them.")
                self.xray.start(build([], []))
                return
            time.sleep(0.1)

    def _forwards(self, cfgs: dict) -> list[forwards_mod.Forward]:
        # Each bad or busy forward is dropped on its own, with a warning.
        forwards, warnings = forwards_mod.prepare(cfgs.get("forwards"), cfgs.get("core"),
                                                  cfgs.get("exits"))
        for warning in warnings:
            self._log(f"WARNING: {warning}")
        return forwards

    def _log_lan_share(self, core_cfg: dict, iface) -> None:
        if not core_cfg.get("allow_lan"):
            return
        port = coreopts.valid_socks_port(core_cfg.get("socks_port"))
        has_auth = bool(core_cfg.get("lan_user")) and bool(core_cfg.get("lan_pass"))
        suffix = "" if has_auth else " (no password!)"
        self._log(f"Local proxy shared on the LAN at {iface.ipv4}:{port}{suffix}")

    def _connect_generic(self, profile: Profile, iface, server_ip: str, dns) -> None:
        self._log("Building runtime config...")
        cfgs = app_settings.load()
        rules = routing.build_rules(cfgs["routing"])
        exits = self._exits(cfgs)
        forwards = self._forwards(cfgs)

        def build(exits, forwards):
            return render.build(profile, iface.alias, routing_rules=rules,
                                domain_strategy=routing.domain_strategy_for(cfgs["routing"]),
                                stats=True, log_level=cfgs.get("log_level"),
                                dns_cfg=cfgs.get("dns"), tun_mtu=cfgs.get("tun_mtu"),
                                server_ip=server_ip, core_cfg=cfgs.get("core"),
                                exits=exits, exits_cfg=cfgs.get("exits"),
                                forwards=forwards)

        cfg = build(exits, forwards)
        self._log_lan_share(cfgs.get("core") or {}, iface)

        self._log("Starting Xray...")
        network.remove_routes(server_ip)
        # Pin the server route first: Xray dials the moment it starts, and
        # until this exists that dial races the default route out of the box.
        network.add_host_route(server_ip, iface.gateway)
        self.xray.start(cfg)
        self._retry_without_extras(build, exits, forwards)

        self._log("Waiting for TUN adapter...")
        tun = network.wait_for_tun(alive=self.xray.is_running)
        if tun is None:
            if not self.xray.is_running():
                # Say why instead of "did not appear": a bad config, port 53
                # already taken, a missing binary... it is all in the log.
                self._fail_connect(server_ip, f"Xray exited during startup: {_last_log_line()}")
            self._fail_connect(server_ip, "TUN interface xray0 did not appear")

        self._log("Configuring tunnel adapter...")
        if not network.configure_tun(tun):
            self._fail_connect(
                server_ip,
                f"could not assign {network.TUN_ADDRESS} to {network.TUN_NAME} — "
                "the tunnel would carry no traffic",
            )

        # Persist backup + a boot restore task BEFORE hijacking DNS. Static
        # 127.0.0.1 survives a power-off; the task puts the adapter back.
        self.state.save(iface, server_ip, tun, dns)
        try:
            bootrestore.install()
        except Exception as exc:
            self._log(f"Boot restore task not registered: {exc}")
        self._log("Routing DNS and traffic through the tunnel...")
        if network.set_dns_loopback(iface.alias) is False:
            self._log("WARNING: DNS could not be routed through the tunnel — "
                      "lookups will leave unencrypted via the local network.")
        network.add_default_routes(tun)
        self._owned = True
        self._setup_gateway()
        self._log("Connected.")

    def _setup_gateway(self) -> None:
        """Optionally share the tunnel with hotspot clients. Never fails the connect."""
        cfg = app_settings.load().get("gateway", {})
        if not cfg.get("enabled") or not hotspot.supported():
            return
        try:
            self._start_gateway(cfg)
        except Exception as exc:
            self._log(f"Gateway mode unavailable: {exc}")

    def start_gateway(self) -> None:
        """Start sharing on the connection that is already up. Raises on failure,
        so the switch that asked for it can say why."""
        if not self.state.is_connected():
            raise RuntimeError("connect first")
        if not hotspot.supported():
            raise RuntimeError("not available on this platform")
        self._start_gateway(app_settings.load().get("gateway", {}))

    def _start_gateway(self, cfg: dict) -> None:
        if IS_WIN:
            self._configure_windows_hotspot(cfg)
            if cfg.get("start_hotspot", True) and hotspot.tethering_state() != "On":
                self._log("Starting Windows hotspot...")
                if not hotspot.start_tethering():
                    raise RuntimeError("Windows would not start the hotspot")
                # Tethering reports "On" a moment before the adapter ICS has
                # to share shows up in the connection list.
                hotspot.wait_for_hotspot_adapter()
            hotspot.enable(public_name=network.TUN_NAME)
        else:
            ssid, password = _hotspot_credentials()
            gw = app_settings.load()["gateway"]
            self._log("Starting Wi-Fi hotspot...")
            ap = hotspot.start_linux(ssid, password, security=str(gw.get("security")),
                                     band_choice=str(gw.get("band")),
                                     hidden=gw.get("hidden") is True,
                                     isolation=gw.get("isolation") is True)
            self._log(f'Hotspot "{ssid}" is on ({ap}); password: {password}')
        self._gateway_on = True
        self.state.set_gateway(True)
        self._log("Gateway mode on — hotspot clients now use the tunnel.")

    def _configure_windows_hotspot(self, cfg: dict) -> None:
        """Push Settings → Hotspot into Windows' own access point settings.

        Windows only reads them when the hotspot starts, so this has to happen
        first; an empty field keeps what Windows already has. Getting this
        wrong must not cost the user gateway mode, so a refusal is logged and
        the hotspot starts on its old name and password."""
        # The saved defaults are never empty, so pushing them unasked renamed a
        # hotspot the user had set up in Windows. Only an edit on the page does.
        if cfg.get("apply_on_windows") is not True:
            return
        ssid, password = str(cfg.get("ssid") or ""), str(cfg.get("password") or "")
        security, band = str(cfg.get("security") or ""), str(cfg.get("band") or "")
        if not (ssid or password or security or band):
            return
        if hotspot.configure_tethering(ssid, password, security=security, band=band):
            self._log(f'Hotspot name and password set ("{ssid}").' if ssid
                      else "Hotspot settings applied.")
            settings = app_settings.load()
            settings["gateway"]["apply_on_windows"] = False
            app_settings.save(settings)
        else:
            self._log("WARNING: Windows kept its own hotspot name and password.")

    def stop_gateway(self) -> None:
        """Turn sharing off without dropping the tunnel."""
        if self._gateway_on:
            hotspot.disable()
            self._gateway_on = False
            self.state.set_gateway(False)

    def _connect_macos(self, profile: Profile, iface, server_ip: str, dns) -> None:
        # Xray has no native TUN inbound on macOS: run it with a SOCKS inbound
        # only, then bridge that to a real TUN device via tun2socks.
        self._log("Building runtime config (macOS: SOCKS + tun2socks bridge)...")
        cfgs = app_settings.load()
        rules = routing.build_rules(cfgs["routing"])
        core_cfg = cfgs.get("core") or {}
        exits = self._exits(cfgs)
        forwards = self._forwards(cfgs)

        def build(exits, forwards):
            return render.build(profile, iface.alias, routing_rules=rules,
                                domain_strategy=routing.domain_strategy_for(cfgs["routing"]),
                                stats=True, include_tun=False, log_level=cfgs.get("log_level"),
                                dns_cfg=cfgs.get("dns"), server_ip=server_ip,
                                core_cfg=core_cfg, exits=exits,
                                exits_cfg=cfgs.get("exits"), forwards=forwards)

        cfg = build(exits, forwards)
        self._log_lan_share(core_cfg, iface)
        # Same validation render already applied to socks-in inside cfg, so
        # the port this process waits on and bridges from is the one Xray
        # actually opened.
        socks_port = coreopts.valid_socks_port(core_cfg.get("socks_port"))

        self._log("Starting Xray...")
        network.remove_routes(server_ip)
        network.add_host_route(server_ip, iface.gateway)
        self.xray.start(cfg)
        self._retry_without_extras(build, exits, forwards)
        if not _wait_port(SOCKS_HOST, socks_port):
            self._fail_connect(server_ip, "Xray SOCKS inbound did not come up")

        self._log("Starting tun2socks bridge...")
        self.tun2socks.start(SOCKS_HOST, socks_port)
        if not t2s.bring_up_device():
            self._fail_connect(server_ip, "tun2socks TUN device did not appear")

        self.state.save(iface, server_ip, 0, dns)
        try:
            bootrestore.install()
        except Exception as exc:
            self._log(f"Boot restore task not registered: {exc}")
        self._log("Routing DNS and traffic through the tunnel...")
        network.set_dns_loopback(iface.alias)
        network.add_default_routes(None)
        self._owned = True
        self._log("Connected.")

    def disconnect(self) -> None:
        if not self.state.is_connected() and not xray_mod.is_xray_running():
            return
        self._restore()

    def cleanup(self) -> None:
        # Explicit "restore network": also clear sharing a previous crash left behind.
        if hotspot.supported() and (app_settings.load().get("gateway", {}).get("enabled")
                                    or self.state.gateway_on()):
            self._gateway_on = True
        self._restore()

    def repair_route_if_needed(self) -> str | None:
        """Refresh the pinned host route if the default gateway moved.

        DHCP renewal, Wi-Fi roaming, or a brief drop to link-local (169.254.x.x)
        can hand out a new gateway while connected. The host route to the
        server is pinned to the gateway seen at connect time, so it silently
        blackholes traffic (repeated 'proxy/tun: operation timed out') until
        something refreshes it — previously only a manual disconnect did.
        """
        if IS_MAC or not self.state.is_connected():
            return None
        iface = network.detect_interface()
        if iface is None or iface.alias != self.state.alias:
            # Offline, or roamed to a different adapter entirely — too risky
            # to auto-migrate DNS/routes across adapters; let the user reconnect.
            return None
        if iface.gateway == self.state.gateway:
            return None
        server_ip = self.state.server_ip
        if not server_ip:
            return None
        old_gateway = self.state.gateway
        network.replace_host_route(server_ip, iface.gateway)
        self.state.update_gateway(iface.gateway)
        msg = f"Gateway changed ({old_gateway} -> {iface.gateway}) — route to server refreshed."
        self._log(msg)
        return msg

    def repair_dns_if_needed(self) -> str | None:
        """Put the tunnel's DNS back if another program cleared it.

        Seen live on Linux: minutes after connecting, xray0's resolved settings
        were wiped without a trace and lookups fell back to other VPNs' servers
        until reconnect. Checked on the same timer as the route.
        """
        if IS_MAC or not self.state.is_connected():
            return None
        restored = network.repair_tun_dns()
        if restored is None:
            return None
        if restored:
            self._dns_warned = False
            msg = "Tunnel DNS was cleared by another program — restored."
        elif self._dns_warned:
            return None  # already said so; do not repeat every 15 seconds
        else:
            self._dns_warned = True
            msg = ("WARNING: tunnel DNS was cleared by another program and could not "
                   "be restored — lookups are leaving outside the tunnel.")
        self._log(msg)
        return msg

    def recover_if_stale(self, dns_retries: int = 8) -> bool:
        """Undo leftover DNS/routes when a previous run never disconnected.

        Static DNS 127.0.0.1 on the Wi-Fi adapter survives reboot. If xray is
        not running, nothing answers it and Windows shows No Internet.
        """
        if not self.state.is_connected():
            return False
        if xray_mod.is_xray_running():
            return False
        self._log("Previous session left DNS pointing at 127.0.0.1. Restoring...")
        self._restore(dns_retries=dns_retries)
        return True

    def _restore(self, dns_retries: int = 1) -> None:
        self._log("Disconnecting...")
        alias = self.state.alias
        server_ip = self.state.server_ip
        dns = self.state.dns_state()
        if self._gateway_on or self.state.gateway_on():
            # Undo first: leaving ICS pointed at a dead tunnel breaks the hotspot.
            try:
                hotspot.disable()
            except Exception:
                pass
            self._gateway_on = False
        if IS_MAC:
            self.tun2socks.stop()
        self.xray.stop()
        network.remove_routes(server_ip)
        if alias:
            network.restore_dns(alias, dns, retries=dns_retries)
        # State records one alias, so an adapter stranded on 127.0.0.1 by an
        # earlier session would otherwise stay broken forever. xray is down by
        # now, so nothing legitimately answers there.
        for stranded in network.release_stranded_dns(exclude=alias):
            self._log(f"Released stale DNS on {stranded}.")
        try:
            bootrestore.uninstall()
        except Exception:
            pass
        self.state.clear()
        self._owned = False
        paths.runtime_config().unlink(missing_ok=True)
        self._log("Network restored.")

    def _atexit(self) -> None:
        # Only auto-restore a connection this process created.
        if self._owned and self.state.is_connected():
            try:
                self._restore()
            except Exception:
                pass


def recover_stale(on_step=None) -> bool:
    """Used by `--restore-stale` (boot task) and by the UI on launch."""
    return Connection(on_step=on_step).recover_if_stale()
