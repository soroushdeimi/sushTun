"""Connect / disconnect orchestrator. Owns cleanup and guarantees restore."""
from __future__ import annotations

import atexit
import hashlib
import json
import secrets
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .. import paths
from . import bootrestore, chains, coreopts, hotspot, network, render, routing
from . import exits as exits_mod
from . import forwards as forwards_mod
from . import settings as app_settings
from . import tun2socks as t2s
from . import xray as xray_mod
from .profiles import Profile, ProfileStore
from .state import MAX_DNS_ATTEMPTS, State

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


def _wait_port(host: str, port: int, timeout: float = 15.0,
               alive: Callable[[], bool] | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if alive is not None and not alive():
            return False
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

    def connect(self, profile: Profile | chains.Chain | chains.ResolvedChain) -> None:
        plan = None
        if isinstance(profile, (chains.Chain, chains.ResolvedChain)):
            try:
                plan = (chains.resolve(profile, ProfileStore().list())
                        if isinstance(profile, chains.Chain) else profile)
                chains.check(plan, app_settings.load().get("core"))
            except ValueError as exc:
                raise ConnectError(str(exc)) from exc
            profile = plan.entry
        if not profile.address or (not profile.id and profile.protocol not in ("http", "socks")):
            raise ConnectError("profile is missing address or id")
        if profile.protocol == "wireguard" and not profile.pbk:
            raise ConnectError("WireGuard profile is missing the peer public key")
        if self.state.is_connected():
            raise ConnectError("already connected")

        self._drain_pending_dns(retries=1)

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
        parked = self.state.pending().get(iface.alias)
        dns = parked.dns if parked else network.backup_dns(iface.alias)

        if IS_MAC:
            self._connect_macos(plan or profile, iface, server_ip, dns)
        else:
            self._connect_generic(plan or profile, iface, server_ip, dns)

    def _fail_connect(self, server_ip: str, reason: str) -> None:
        """Tear down a half-built connection, then report why it failed."""
        self.tun2socks.stop()
        self.xray.stop()
        network.remove_routes(server_ip)
        paths.runtime_config().unlink(missing_ok=True)
        raise ConnectError(reason)

    def _start_xray(self, cfg_path: Path, server_ip: str) -> None:
        """Turn a failed binary launch into a connect error after cleanup."""
        try:
            self.xray.start(cfg_path)
        except OSError as exc:
            self._fail_connect(server_ip, f"Could not start Xray: {exc}")

    def _exits(self, cfgs: dict) -> list[exits_mod.Exit]:
        # A bad or busy multi-exit setting is dropped here with a warning;
        # it must never keep the main connection from starting.
        exits, warning = exits_mod.prepare(cfgs.get("exits"), cfgs.get("core"),
                                           ProfileStore().get)
        if warning:
            self._log(f"WARNING: {warning}")
        return exits

    def _retry_without_extras(self, build, exits, forwards, server_ip: str) -> None:
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
                self._start_xray(build([], []), server_ip)
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

    def _connect_generic(self, profile: Profile | chains.ResolvedChain, iface, server_ip: str, dns) -> None:
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
        try:
            network.add_host_route(server_ip, iface.gateway)
        except (OSError, RuntimeError) as exc:
            self._fail_connect(server_ip, f"Could not pin the server route: {exc}")
        self._start_xray(cfg, server_ip)
        self._retry_without_extras(build, exits, forwards, server_ip)

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

        # Validate capture before saving connected state or changing DNS.
        try:
            network.add_default_routes(tun)
        except (OSError, RuntimeError) as exc:
            self._fail_connect(server_ip, f"Could not install tunnel routes: {exc}")

        # Persist backup + a boot restore task BEFORE hijacking DNS. Static
        # 127.0.0.1 survives a power-off; the task puts the adapter back.
        self.state.save(iface, server_ip, tun, dns,
                        profile_uid=profile.exit.uid if isinstance(profile, chains.ResolvedChain)
                        else profile.uid,
                        chain_uid=profile.uid if isinstance(profile, chains.ResolvedChain) else "")
        self.state.clear_pending(iface.alias)
        try:
            bootrestore.install()
        except Exception as exc:
            self._log(f"Boot restore task not registered: {exc}")
        self._log("Routing DNS and traffic through the tunnel...")
        if network.set_dns_loopback(iface.alias) is False:
            self._log("WARNING: DNS could not be routed through the tunnel — "
                      "lookups will leave unencrypted via the local network.")
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
            self._start_windows_hotspot(cfg)
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

    def _start_windows_hotspot(self, cfg: dict) -> None:
        """Run the Mobile Hotspot on the tunnel's connection.

        Windows shares whichever connection the hotspot was started from, so
        a hotspot already running (started by the user, on Wi-Fi) is
        restarted on the tunnel and handed back to Wi-Fi when sharing ends."""
        if self.state.tethering() and hotspot.tethering_state(network.TUN_NAME) == "On":
            return  # already ours and on the tunnel
        self._configure_windows_hotspot(cfg)
        was_on = hotspot.tethering_state() == "On"
        if not was_on and not cfg.get("start_hotspot", True):
            raise RuntimeError("the Windows hotspot is off — turn it on first")
        if was_on:
            self._log("Moving the Windows hotspot onto the tunnel...")
            hotspot.stop_tethering()
        else:
            self._log("Starting Windows hotspot...")
        if not hotspot.start_tethering(network.TUN_NAME):
            if was_on:
                hotspot.start_tethering(self.state.alias or "")  # give it back
            raise RuntimeError("Windows would not run the hotspot on the tunnel")
        self.state.set_tethering("moved" if was_on else "started")

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
        # The window keeps its own copy of the settings and saves it whole, so
        # the cleared flag below came back on the next save and every connect
        # pushed the same values again. What was pushed last is remembered
        # here, where the window cannot overwrite it.
        pushed = hashlib.sha256(
            json.dumps([ssid, password, security, band]).encode("utf-8")).hexdigest()
        if self.state.hotspot_pushed() == pushed:
            return
        if hotspot.configure_tethering(ssid, password, security=security, band=band):
            self._log(f'Hotspot name and password set ("{ssid}").' if ssid
                      else "Hotspot settings applied.")
            self.state.set_hotspot_pushed(pushed)
            settings = app_settings.load()
            settings["gateway"]["apply_on_windows"] = False
            app_settings.save(settings)
        else:
            self._log("WARNING: Windows kept its own hotspot name and password.")

    def stop_gateway(self) -> None:
        """Turn sharing off without dropping the tunnel."""
        # The flag on disk too: after an app restart the switch must still
        # be able to turn off a hotspot the previous run left sharing.
        if self._gateway_on or self.state.gateway_on():
            self._stop_sharing()
            self._gateway_on = False
            self.state.set_gateway(False)

    def _stop_sharing(self) -> None:
        if not IS_WIN:
            hotspot.disable()
            return
        how = self.state.tethering()
        self.state.set_tethering("")
        if not how:
            return  # not ours: a hotspot the user runs stays as it is
        if not hotspot.stop_tethering(network.TUN_NAME):
            self._log("WARNING: Windows would not switch the hotspot off.")
        elif how == "moved":
            # It was the user's, running on their own connection before.
            if not hotspot.start_tethering(self.state.alias or ""):
                self._log("WARNING: the Windows hotspot could not be put back on "
                          "this computer's own connection.")

    def _connect_macos(self, profile: Profile | chains.ResolvedChain, iface, server_ip: str, dns) -> None:
        # Xray's own TUN inbound first (a utun device, the same model as
        # Linux/Windows): measured on an M-series Mac it moved the same traffic
        # with ~24% less CPU than tun2socks, and it is one process instead of
        # two. The tun2socks bridge stays as the fallback for a core that
        # cannot open the device.
        other = network.mac_other_vpn(iface.alias)
        if other:
            self._log(f"Another VPN is active on {other}; sushTun's routes take priority, "
                      "and that VPN keeps only its own narrower routes.")
        self._log("Building runtime config...")
        cfgs = app_settings.load()
        rules = routing.build_rules(cfgs["routing"])
        core_cfg = cfgs.get("core") or {}
        exits = self._exits(cfgs)
        forwards = self._forwards(cfgs)
        native = True

        def build(exits, forwards):
            return render.build(profile, iface.alias, routing_rules=rules,
                                domain_strategy=routing.domain_strategy_for(cfgs["routing"]),
                                stats=True, include_tun=native, tun_name=t2s.DEVICE,
                                tun_mtu=cfgs.get("tun_mtu"), log_level=cfgs.get("log_level"),
                                dns_cfg=cfgs.get("dns"), server_ip=server_ip,
                                core_cfg=core_cfg, exits=exits,
                                exits_cfg=cfgs.get("exits"), forwards=forwards)

        cfg = build(exits, forwards)
        self._log_lan_share(core_cfg, iface)
        self._log("Starting Xray...")
        network.remove_routes(server_ip)
        t2s.kill_stale()  # a crashed bridge session would still hold the device
        network.add_host_route(server_ip, iface.gateway)
        if network.mac_ensure_scoped_default(iface.alias, iface.gateway):
            self._log(f"Restored the missing default route scoped to {iface.alias}.")
        self._start_xray(cfg, server_ip)
        self._retry_without_extras(build, exits, forwards, server_ip)
        if not network.mac_wait_for_device(alive=self.xray.is_running):
            why = (_last_log_line() if not self.xray.is_running()
                   else f"{t2s.DEVICE} did not appear")
            self._log(f"Native TUN unavailable ({why}); using the tun2socks bridge.")
            native = False
            self.xray.stop()
            self._start_macos_bridge(build, exits, forwards, core_cfg, server_ip)

        self.state.save(iface, server_ip, 0, dns,
                        profile_uid=profile.exit.uid if isinstance(profile, chains.ResolvedChain)
                        else profile.uid,
                        chain_uid=profile.uid if isinstance(profile, chains.ResolvedChain) else "")
        self.state.clear_pending(iface.alias)
        try:
            bootrestore.install()
        except Exception as exc:
            self._log(f"Boot restore task not registered: {exc}")
        self._log("Routing DNS and traffic through the tunnel...")
        if network.set_dns_loopback(iface.alias) is False:
            self._log("WARNING: DNS could not be routed through the tunnel — "
                      "lookups will leave unencrypted via the local network.")
        try:
            network.mac_add_split_routes(native)
        except (OSError, RuntimeError) as exc:
            self._restore()
            raise ConnectError(f"Could not install tunnel routes: {exc}") from exc
        # A route that failed to go in (another VPN's routes, a stale device)
        # used to go unnoticed: "Connected", with nothing in the tunnel.
        routed = network.mac_route_device("1.1.1.1")
        if routed != t2s.DEVICE:
            self._restore()
            raise ConnectError(f"traffic is still routed through {routed or 'nothing'}, "
                               f"not the tunnel ({t2s.DEVICE}) — another VPN is holding "
                               "more specific routes; disconnect it first")
        self._owned = True
        self._log("Connected.")

    def _start_macos_bridge(self, build, exits, forwards, core_cfg: dict,
                            server_ip: str) -> None:
        """Xray with a SOCKS inbound only, bridged to the utun by tun2socks."""
        # Same validation render already applied to socks-in, so the port this
        # waits on and bridges from is the one Xray actually opened.
        socks_port = coreopts.valid_socks_port(core_cfg.get("socks_port"))
        self._start_xray(build(exits, forwards), server_ip)
        self._retry_without_extras(build, exits, forwards, server_ip)
        if not _wait_port(SOCKS_HOST, socks_port, alive=self.xray.is_running):
            if not self.xray.is_running():
                self._fail_connect(server_ip, f"Xray exited during startup: {_last_log_line()}")
            self._fail_connect(server_ip, "Xray SOCKS inbound did not come up")
        self._log("Starting tun2socks bridge...")
        self.tun2socks.start(SOCKS_HOST, socks_port)
        if not t2s.bring_up_device(alive=self.tun2socks.is_running):
            self._fail_connect(server_ip, "tun2socks TUN device did not appear: "
                                          f"{t2s.last_log_line()}")

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
        if not self.state.is_connected():
            return None
        iface = network.detect_interface()
        if iface is None or iface.alias != self.state.alias:
            # Offline, or roamed to a different adapter entirely — too risky
            # to auto-migrate DNS/routes across adapters; let the user reconnect.
            return None
        restored = None
        if network.repair_tun_routes():
            restored = "Missing tunnel routes restored."
            self._log(restored)
        if iface.gateway == self.state.gateway:
            return restored
        server_ip = self.state.server_ip
        if not server_ip:
            return None
        old_gateway = self.state.gateway
        network.replace_host_route(server_ip, iface.gateway)
        if IS_MAC:
            network.mac_ensure_scoped_default(iface.alias, iface.gateway)
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
        if xray_mod.is_xray_running():
            return False
        if not self.state.is_connected():
            return self._drain_pending_dns(retries=dns_retries)
        self._log("Previous session left DNS pointing at 127.0.0.1. Restoring...")
        return self._restore(dns_retries=dns_retries)

    def _uninstall_boot_if_done(self) -> None:
        if not self.state.pending():
            try:
                bootrestore.uninstall()
            except Exception:
                pass

    def _drain_pending_dns(self, retries: int) -> bool:
        entries = self.state.pending()
        if not entries:
            return False
        restored = True
        for alias, parked in entries.items():
            try:
                success = network.restore_dns(alias, parked.dns, retries=retries)
            except Exception as exc:
                success = False
                self._log(f"WARNING: DNS recovery for {alias} failed: {exc}")
            if success:
                self.state.clear_pending(alias)
                continue
            restored = False
            attempts = parked.attempts + 1
            # Check existence after the retries: boot may precede adapter startup.
            try:
                exists = network.dns_target_exists(alias, parked.dns)
            except Exception:
                exists = None  # A failed inventory is not evidence of removal.
            if exists is False or attempts >= MAX_DNS_ATTEMPTS:
                self.state.clear_pending(alias)
                self._log(f"WARNING: dropping DNS backup for {alias}: adapter/service gone "
                          f"or {MAX_DNS_ATTEMPTS} failed recovery calls.")
            else:
                self.state.save_pending(alias, parked.dns, attempts=attempts)
                self._log(f"WARNING: saved DNS for {alias} still could not be restored.")
        if not restored:
            try:
                network.release_stranded_dns(exclude=None)
            except Exception as exc:
                self._log(f"WARNING: stranded DNS release failed: {exc}")
        self._uninstall_boot_if_done()
        return restored

    def _restore(self, dns_retries: int = 1) -> bool:
        self._log("Disconnecting...")
        alias = self.state.alias
        server_ip = self.state.server_ip
        dns = self.state.dns_state()
        if self._gateway_on or self.state.gateway_on():
            # Undo first, while the tunnel still exists: a hotspot left
            # sharing it would have nothing behind it once it is gone.
            try:
                self._stop_sharing()
            except Exception:
                pass
            self._gateway_on = False
        cleanup_ok = True
        # The bridge exists only on macOS; its stale-process sweep uses pkill.
        actions = [self.xray.stop, lambda: network.remove_routes(server_ip)]
        if IS_MAC:
            actions.insert(0, self.tun2socks.stop)
        for action in actions:
            try:
                action()
            except Exception as exc:
                cleanup_ok = False
                self._log(f"WARNING: teardown operation failed: {exc}")
        restored = True
        try:
            if alias:
                try:
                    restored = network.restore_dns(alias, dns, retries=dns_retries) is not False
                except Exception as exc:
                    restored = False
                    self._log(f"WARNING: DNS restore failed: {exc}")
                if not restored:
                    self.state.save_pending(alias, dns)
                    self._log("WARNING: DNS restore failed; backup saved for later recovery.")
                else:
                    self.state.clear_pending(alias)
            # Include the active adapter when its own restore failed.
            try:
                for stranded in network.release_stranded_dns(exclude=alias if restored else None):
                    self._log(f"Released stale DNS on {stranded}.")
            except Exception as exc:
                cleanup_ok = False
                self._log(f"WARNING: stranded DNS release failed: {exc}")
            self._uninstall_boot_if_done()
        finally:
            try:
                self.state.clear()
            finally:
                self._owned = False
                paths.runtime_config().unlink(missing_ok=True)
        if restored and cleanup_ok and not self.state.pending():
            self._log("Network restored.")
        return restored and cleanup_ok

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
