"""Gateway mode: share the tunnel with devices on a Wi-Fi hotspot.

Windows Internet Connection Sharing (ICS) NATs a "private" adapter behind a
"public" one. Pointing the public side at the Xray TUN adapter makes every
hotspot client reach the internet through the tunnel with no client-side setup.
Driven through PowerShell rather than a COM binding so the app keeps its
stdlib-only runtime footprint.

On Linux, NetworkManager's "shared" mode does the same job (see the Linux
section below).
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import proc
from .network import TUN_NAME

IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


def supported() -> bool:
    return IS_WIN or IS_LINUX

# ICS sharing roles, per SHARINGCONNECTIONTYPE.
PUBLIC = 0   # the connection to the internet (our tunnel)
PRIVATE = 1  # the connection clients sit on (the hotspot)

_LIST_PS = """
$m = New-Object -ComObject HNetCfg.HNetShare
$out = @()
foreach ($c in $m.EnumEveryConnection) {
  $p = $m.NetConnectionProps($c)
  $cfg = $m.INetSharingConfigurationForINetConnection($c)
  $out += [pscustomobject]@{
    name = $p.Name; status = [int]$p.Status; device = $p.DeviceName
    shared = [bool]$cfg.SharingEnabled; role = [int]$cfg.SharingConnectionType
  }
}
$out | ConvertTo-Json -Compress
"""

_SET_PS = """
$pub = $env:PUBLIC_NAME; $priv = $env:PRIVATE_NAME
$m = New-Object -ComObject HNetCfg.HNetShare
foreach ($c in $m.EnumEveryConnection) {
  $cfg = $m.INetSharingConfigurationForINetConnection($c)
  if ($cfg.SharingEnabled) { $cfg.DisableSharing() }
}
$done = 0
foreach ($c in $m.EnumEveryConnection) {
  $p = $m.NetConnectionProps($c)
  $cfg = $m.INetSharingConfigurationForINetConnection($c)
  if ($p.Name -eq $pub)  { $cfg.EnableSharing(0); $done++ }
  if ($p.Name -eq $priv) { $cfg.EnableSharing(1); $done++ }
}
if ($done -lt 2) { exit 1 }
"""

_CLEAR_PS = """
$m = New-Object -ComObject HNetCfg.HNetShare
foreach ($c in $m.EnumEveryConnection) {
  $cfg = $m.INetSharingConfigurationForINetConnection($c)
  if ($cfg.SharingEnabled) { $cfg.DisableSharing() }
}
"""

# Modern adapters reject the legacy hostednetwork API, so drive the same
# Mobile Hotspot surface the Settings app uses.
_TETHER_PS = """
$action = $env:TETHER_ACTION
[void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking, ContentType=WindowsRuntime]
[void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking, ContentType=WindowsRuntime]
$profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if (-not $profile) { Write-Output 'no-profile'; exit 1 }
$mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
if ($action -eq 'status') { Write-Output $mgr.TetheringOperationalState; exit 0 }

$task = if ($action -eq 'start') { $mgr.StartTetheringAsync() } else { $mgr.StopTetheringAsync() }
$deadline = (Get-Date).AddSeconds(20)
while ($task.Status -eq 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
if ($task.Status -ne 1) { Write-Output "async-status=$($task.Status)"; exit 1 }
Write-Output $mgr.TetheringOperationalState
"""


@dataclass
class Connection:
    name: str
    status: int
    shared: bool
    role: int

    @property
    def connected(self) -> bool:
        return self.status == 2  # NCS_CONNECTED


def list_connections() -> list[Connection]:
    if not IS_WIN:
        return []
    out = proc.powershell(_LIST_PS, timeout=30).stdout.strip()
    try:
        data = json.loads(out)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        Connection(name=d.get("name", ""), status=int(d.get("status", 0)),
                   shared=bool(d.get("shared")), role=int(d.get("role", 0)))
        for d in data
    ]


def find_hotspot_adapter(connections: list[Connection] | None = None) -> str | None:
    """The ICS-side adapter the hotspot runs on, e.g. 'Local Area Connection* 3'."""
    for c in connections if connections is not None else list_connections():
        if c.name.startswith("Local Area Connection*") and c.connected:
            return c.name
    return None


def is_sharing() -> bool:
    if IS_LINUX:
        return _linux_running()
    return any(c.shared for c in list_connections())


def _ensure_tunnel_dns(adapter: str) -> None:
    """Give the tunnel adapter a resolver.

    ICS answers client DNS from the shared connection's servers, and the TUN
    adapter comes up with none — without this, hotspot clients resolve nothing.
    127.0.0.1 is Xray's own dns inbound.
    """
    proc.run(["netsh", "interface", "ipv4", "set", "dnsservers",
              f"name={adapter}", "static", "127.0.0.1", "primary", "validate=no"])


def enable(public_name: str = TUN_NAME, private_name: str | None = None) -> None:
    """Route hotspot clients through `public_name`. Raises if it cannot be set."""
    if not IS_WIN:
        raise RuntimeError("gateway mode is only implemented on Windows")
    connections = list_connections()
    if not connections:
        raise RuntimeError("cannot enumerate network connections (needs admin)")
    private_name = private_name or find_hotspot_adapter(connections)
    if not private_name:
        raise RuntimeError("no active hotspot adapter found — turn the hotspot on first")
    if not any(c.name == public_name for c in connections):
        raise RuntimeError(f"tunnel adapter {public_name!r} not found")
    _ensure_tunnel_dns(public_name)
    result = proc.powershell(
        _SET_PS, env={"PUBLIC_NAME": public_name, "PRIVATE_NAME": private_name}, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError("failed to enable internet connection sharing")

    # Windows can accept the calls yet leave sharing off (a link-local public
    # adapter is one way this happens), so confirm rather than assume.
    after = {c.name: c for c in list_connections()}
    pub, priv = after.get(public_name), after.get(private_name)
    if not (pub and pub.shared and pub.role == PUBLIC):
        raise RuntimeError(f"Windows did not accept {public_name!r} as the shared connection")
    if not (priv and priv.shared and priv.role == PRIVATE):
        raise RuntimeError(f"Windows did not accept {private_name!r} as the hotspot side")


def disable() -> None:
    if IS_WIN:
        proc.powershell(_CLEAR_PS, timeout=60)
    elif IS_LINUX:
        stop_linux()


def tethering_state() -> str:
    if not IS_WIN:
        return "unavailable"
    r = proc.powershell(_TETHER_PS, env={"TETHER_ACTION": "status"}, timeout=30)
    return r.stdout.strip() or "unknown"


def start_tethering() -> bool:
    r = proc.powershell(_TETHER_PS, env={"TETHER_ACTION": "start"}, timeout=60)
    return r.returncode == 0


def stop_tethering() -> bool:
    r = proc.powershell(_TETHER_PS, env={"TETHER_ACTION": "stop"}, timeout=60)
    return r.returncode == 0


# -- Linux -----------------------------------------------------------------
# NetworkManager's "shared" IPv4 method is ICS: DHCP and DNS for clients
# (dnsmasq, which asks the host resolver, so the tunnel's DNS), IP forwarding,
# and NAT out of whatever the routing table picks, which while connected is
# the tunnel's two /1 routes. So a shared hotspot is all gateway mode needs.

AP_IFACE = "sushap0"
AP_CON = "sushTun Hotspot"
_FORWARDING = "/proc/sys/net/ipv4/conf/{}/forwarding"


def _set_forwarding(iface: str, on: bool) -> None:
    # NetworkManager 1.50+ turns forwarding on per interface, and only on the
    # devices it manages. The tunnel is unmanaged, so replies coming back out
    # of it were dropped instead of forwarded: hotspot clients could send but
    # never got an answer.
    try:
        Path(_FORWARDING.format(iface)).write_text("1" if on else "0", encoding="ascii")
    except OSError:
        pass


def _wifi_devices() -> list[tuple[str, str]]:
    """(device, state) of each Wi-Fi adapter NetworkManager knows."""
    out = proc.run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"]).stdout
    found = []
    for line in out.splitlines():
        dev, _, rest = line.partition(":")
        kind, _, state = rest.partition(":")
        if kind == "wifi" and dev != AP_IFACE:
            found.append((dev, state))
    return found


def _iw_info(dev: str) -> tuple[int | None, int | None, int | None]:
    """(wiphy, channel, MHz) of a Wi-Fi interface, from `iw dev <dev> info`."""
    out = proc.run(["iw", "dev", dev, "info"]).stdout
    phy = re.search(r"^\s*wiphy (\d+)", out, re.M)
    chan = re.search(r"^\s*channel (\d+) \((\d+) MHz\)", out, re.M)
    return (int(phy.group(1)) if phy else None,
            int(chan.group(1)) if chan else None,
            int(chan.group(2)) if chan else None)


def _can_ap_while_connected(phy: int) -> bool:
    """Does the radio allow an access point beside a client interface?

    From `iw phy phyN info`, e.g. "#{ managed, P2P-client } <= 2, #{ AP } <= 1,
    ... #channels <= 1": one combination must hold both a managed and an AP
    interface. Entries start with "*" and may wrap onto indented lines.
    """
    lines = proc.run(["iw", "phy", f"phy{phy}", "info"]).stdout.splitlines()
    start = next((i for i, ln in enumerate(lines) if "valid interface combinations" in ln), None)
    if start is None:
        return False
    combos: list[str] = []
    for ln in lines[start + 1:]:
        if not ln.startswith("\t\t"):
            break
        if ln.strip().startswith("*"):
            combos.append(ln.strip())
        elif combos:
            combos[-1] += " " + ln.strip()
    return any("managed" in c and re.search(r"#\{[^}]*\bAP\b[^}]*\}", c) for c in combos)


def _local_mac(dev: str) -> str | None:
    """dev's MAC with the locally-administered bit set: most drivers refuse a
    second interface on the radio with the same address as the first."""
    try:
        mac = Path(f"/sys/class/net/{dev}/address").read_text(encoding="utf-8").strip()
        first, rest = mac.split(":", 1)
    except (OSError, ValueError):
        return None
    return f"{int(first, 16) | 0x02:02x}:{rest}"


def _wait_for_nm_device(dev: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(d == dev for d, _ in _wifi_devices_all()):
            return
        time.sleep(0.5)


def _wifi_devices_all() -> list[tuple[str, str]]:
    out = proc.run(["nmcli", "-t", "-f", "DEVICE,STATE", "device", "status"]).stdout
    return [tuple(line.split(":", 1)) for line in out.splitlines() if ":" in line]


def _linux_running() -> bool:
    out = proc.run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"]).stdout
    return AP_CON in out.splitlines()


SECURITY_CHOICES = ("wpa2", "wpa3")
BAND_CHOICES = ("auto", "bg", "a")


def start_linux(ssid: str, password: str, *, security: str = "wpa2", band_choice: str = "auto",
                hidden: bool = False, isolation: bool = False) -> str:
    """Bring up a NetworkManager hotspot. Returns the interface it runs on.

    The keyword options come from Settings → Hotspot; their defaults give the
    same hotspot as before they existed. An unknown value falls back to its
    default rather than failing."""
    if security not in SECURITY_CHOICES:
        security = "wpa2"
    if band_choice not in BAND_CHOICES:
        band_choice = "auto"
    devices = _wifi_devices()
    if not devices:
        raise RuntimeError("no Wi-Fi adapter found")
    dev, state = devices[0]
    ap, band, channel = dev, None, None
    if state == "connected":
        # Turning the adapter itself into an access point would drop the Wi-Fi
        # it is connected to, very likely the internet the tunnel runs over.
        # A second, virtual AP interface keeps both, if the radio allows it,
        # and only on the channel the client side is already using.
        phy, channel, mhz = _iw_info(dev)
        if phy is None or channel is None or not _can_ap_while_connected(phy):
            raise RuntimeError(
                f"{dev} cannot run a hotspot while it is connected to Wi-Fi; "
                "use Ethernet for internet, or disconnect Wi-Fi first")
        band = "a" if mhz and mhz > 4000 else "bg"
        if proc.run(["iw", "dev", AP_IFACE, "info"]).returncode != 0:
            add = ["iw", "dev", dev, "interface", "add", AP_IFACE, "type", "__ap"]
            mac = _local_mac(dev)
            if mac:
                add += ["addr", mac]
            if proc.run(add).returncode != 0:
                raise RuntimeError(f"could not add a virtual hotspot interface to {dev}")
        ap = AP_IFACE
        _wait_for_nm_device(AP_IFACE)
        proc.run(["nmcli", "device", "set", AP_IFACE, "managed", "yes"])

    proc.run(["nmcli", "connection", "delete", AP_CON])  # a leftover from a crash
    add = ["nmcli", "connection", "add", "type", "wifi", "ifname", ap, "con-name", AP_CON,
           "autoconnect", "no", "ssid", ssid, "802-11-wireless.mode", "ap",
           # IPv6 off: the tunnel carries IPv4 only, so shared IPv6 would hand
           # clients a path around it.
           "ipv4.method", "shared", "ipv6.method", "disabled",
           # WPA2 with AES only. Left to NetworkManager's defaults the hotspot
           # also offered WPA1 and the TKIP cipher, and phones labelled it
           # "weak security".
           "wifi-sec.key-mgmt", "sae" if security == "wpa3" else "wpa-psk",
           "wifi-sec.proto", "rsn",
           "wifi-sec.pairwise", "ccmp", "wifi-sec.group", "ccmp",
           "wifi-sec.psk", password]
    if security == "wpa3":
        # WPA3 requires protected management frames. Whether the card can run
        # SAE as an access point is only known when NetworkManager tries.
        add += ["wifi-sec.pmf", "required"]
    if band:
        # One radio: the hotspot must stay on the uplink's own channel, so the
        # band setting only applies when the computer isn't on Wi-Fi.
        add += ["802-11-wireless.band", band, "802-11-wireless.channel", str(channel)]
    elif band_choice != "auto":
        add += ["802-11-wireless.band", band_choice]
    if hidden:
        add += ["802-11-wireless.hidden", "yes"]
    if isolation:
        add += ["802-11-wireless.ap-isolation", "1"]
    if proc.run(add).returncode != 0:
        stop_linux()
        raise RuntimeError("NetworkManager refused the hotspot profile")
    up = proc.run(["nmcli", "connection", "up", AP_CON], timeout=45)
    if up.returncode != 0:
        stop_linux()
        detail = ((up.stderr or "") + (up.stdout or "")).strip().splitlines()
        raise RuntimeError("hotspot did not start" + (f": {detail[-1]}" if detail else ""))
    _set_forwarding(TUN_NAME, True)
    return ap


def stop_linux() -> None:
    """Take the hotspot down. Must run before the tunnel goes: left up, its
    clients would be NATed straight out of the physical link, unprotected."""
    _set_forwarding(TUN_NAME, False)
    proc.run(["nmcli", "connection", "down", AP_CON])
    proc.run(["nmcli", "connection", "delete", AP_CON])
    if proc.run(["iw", "dev", AP_IFACE, "info"]).returncode == 0:
        proc.run(["iw", "dev", AP_IFACE, "del"])
