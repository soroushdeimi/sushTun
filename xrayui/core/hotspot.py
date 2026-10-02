"""Gateway mode: share the tunnel with devices on a Wi-Fi hotspot.

On Windows the Mobile Hotspot -- the one in the Settings app -- is started
from the tunnel adapter's own connection profile, so Windows itself NATs its
clients out through the tunnel. Driven through PowerShell rather than a WinRT
binding so the app keeps its stdlib-only runtime footprint.

On Linux, NetworkManager's "shared" mode does the same job (see the Linux
section below).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

from . import proc
from .network import TUN_NAME

IS_WIN = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")


def supported() -> bool:
    return IS_WIN or IS_LINUX

# Start, stop or read the Mobile Hotspot, sharing the connection of adapter
# $env:TETHER_SOURCE, or Windows' internet connection when that is empty.
#
# Sharing the tunnel used to mean starting the hotspot on Wi-Fi and pointing
# legacy ICS (HNetCfg) at the tunnel afterwards. Next to the Mobile Hotspot,
# Windows 11 refuses every EnableSharing call with 0x80040201, so the hotspot
# never shared the tunnel at all. Starting it from the tunnel's profile does
# the NAT with no ICS involved (verified with a phone on Windows 11).
#
# A freshly created tunnel has no connection profile until Windows has
# identified its network, which takes a few seconds; hence the wait. Stop and
# status fall back to the internet profile when the source is gone (the
# tunnel died with the app), since there is only one hotspot to stop.
#
# Windows PowerShell 5.1 hands WinRT async operations back as a bare
# System.__ComObject: it has no .Status to read, and it cannot be cast to
# IAsyncOperation to await either. So fire the operation, keep a reference to
# it, and poll the manager for the effect it should have had.
_TETHER_PS = """
$action = $env:TETHER_ACTION
[void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking, ContentType=WindowsRuntime]
[void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking, ContentType=WindowsRuntime]
$NI = [Windows.Networking.Connectivity.NetworkInformation]
$prof = $null
if ($env:TETHER_SOURCE) {
  $adapter = Get-NetAdapter -Name $env:TETHER_SOURCE -ErrorAction SilentlyContinue
  if ($adapter) {
    $deadline = (Get-Date).AddSeconds($(if ($action -eq 'start') { 20 } else { 0 }))
    do {
      $prof = $NI::GetConnectionProfiles() | Where-Object {
        $_.NetworkAdapter -and "{$($_.NetworkAdapter.NetworkAdapterId)}" -eq "$($adapter.InterfaceGuid)"
      } | Select-Object -First 1
      if (-not $prof -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    } while (-not $prof -and (Get-Date) -lt $deadline)
  }
  if (-not $prof -and $action -eq 'start') { Write-Output 'no-profile'; exit 1 }
}
if (-not $prof) { $prof = $NI::GetInternetConnectionProfile() }
if (-not $prof) { Write-Output 'no-profile'; exit 1 }
$mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($prof)
if ($action -eq 'status') { Write-Output $mgr.TetheringOperationalState; exit 0 }

$want = if ($action -eq 'start') { 'On' } else { 'Off' }
$state = "$($mgr.TetheringOperationalState)"
if ($state -eq $want) { Write-Output $state; exit 0 }
$op = if ($action -eq 'start') { $mgr.StartTetheringAsync() } else { $mgr.StopTetheringAsync() }
$deadline = (Get-Date).AddSeconds(30)
do {
  Start-Sleep -Milliseconds 400
  $state = "$($mgr.TetheringOperationalState)"
} while ($state -ne $want -and (Get-Date) -lt $deadline)
Write-Output $state
if ($state -ne $want) { exit 1 }
"""

# Read or rewrite the Mobile Hotspot's name, password and radio. Windows keeps
# one access point configuration for the machine -- the same one the Settings
# app edits -- so this is what "customise the hotspot" means here.
_AP_PS = """
[void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking, ContentType=WindowsRuntime]
[void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking, ContentType=WindowsRuntime]
[void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration, Windows.Networking, ContentType=WindowsRuntime]
$prof = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
if (-not $prof) { Write-Output 'no-profile'; exit 1 }
$mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($prof)
$cur = $mgr.GetCurrentAccessPointConfiguration()
if ($env:AP_ACTION -eq 'read') {
  [pscustomobject]@{
    ssid = $cur.Ssid; password = $cur.Passphrase
    band = "$($cur.Band)"; auth = "$($cur.AuthenticationKind)"
  } | ConvertTo-Json -Compress
  exit 0
}

$cfg = New-Object Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration
$cfg.Ssid = if ($env:AP_SSID) { $env:AP_SSID } else { $cur.Ssid }
$cfg.Passphrase = if ($env:AP_PASS) { $env:AP_PASS } else { $cur.Passphrase }
# A band or authentication kind the radio does not offer is dropped instead of
# failing the whole call, so a WPA3 pick on a WPA2-only card still saves the
# name and password.
$cfg.Band = $cur.Band
if ($env:AP_BAND) {
  $b = [Windows.Networking.NetworkOperators.TetheringWiFiBand]::($env:AP_BAND)
  if ($cur.IsBandSupported($b)) { $cfg.Band = $b }
}
$cfg.AuthenticationKind = $cur.AuthenticationKind
if ($env:AP_AUTH) {
  $a = [Windows.Networking.NetworkOperators.TetheringWiFiAuthenticationKind]::($env:AP_AUTH)
  if ($cur.IsAuthenticationKindSupported($a)) { $cfg.AuthenticationKind = $a }
}
$op = $mgr.ConfigureAccessPointAsync($cfg)
$deadline = (Get-Date).AddSeconds(20)
do {
  Start-Sleep -Milliseconds 300
  $now = $mgr.GetCurrentAccessPointConfiguration()
  $applied = $now.Ssid -eq $cfg.Ssid -and $now.Passphrase -eq $cfg.Passphrase
} while (-not $applied -and (Get-Date) -lt $deadline)
if (-not $applied) { Write-Output 'not-applied'; exit 1 }
Write-Output "$($now.Ssid)"
"""

# Settings → Hotspot speaks nmcli's vocabulary; Windows has its own names for
# the same two choices. A value with no Windows equivalent maps to None, which
# leaves that part of the configuration as it is.
WIN_BANDS = {"auto": "Auto", "bg": "TwoPointFourGigahertz", "a": "FiveGigahertz"}
WIN_AUTH = {"wpa2": "Wpa2", "wpa3": "Wpa3"}


def disable() -> None:
    """Linux: take the shared hotspot down. Windows has nothing to undo here:
    its sharing is the hotspot itself (see stop_tethering)."""
    if IS_LINUX:
        stop_linux()


def _tether(action: str, source: str, timeout: int) -> subprocess.CompletedProcess:
    return proc.powershell(_TETHER_PS, env={"TETHER_ACTION": action, "TETHER_SOURCE": source},
                           timeout=timeout)


def tethering_state(source: str = "") -> str:
    if not IS_WIN:
        return "unavailable"
    return _tether("status", source, 30).stdout.strip() or "unknown"


def start_tethering(source: str = "") -> bool:
    """Turn the Mobile Hotspot on, sharing adapter `source` (Windows' internet
    connection when empty), and only return once it is on."""
    return _tether("start", source, 90).returncode == 0


def stop_tethering(source: str = "") -> bool:
    return _tether("stop", source, 90).returncode == 0


def tethering_config() -> dict | None:
    """The Mobile Hotspot's current name, password, band and security, or None
    if Windows won't say (no internet connection profile, mostly)."""
    if not IS_WIN:
        return None
    r = proc.powershell(_AP_PS, env={"AP_ACTION": "read"}, timeout=30)
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout.strip())
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def configure_tethering(ssid: str = "", password: str = "", *,
                        security: str = "", band: str = "") -> bool:
    """Rewrite the Mobile Hotspot's access point configuration.

    Every argument is optional and an empty one keeps what Windows has, so a
    user who only renamed the network keeps their existing password. Windows
    applies this to the hotspot as a whole, exactly as its own Settings app
    does, and a running hotspot has to be restarted to pick it up."""
    if not IS_WIN:
        return False
    env = {"AP_ACTION": "apply", "AP_SSID": ssid, "AP_PASS": password,
           "AP_BAND": WIN_BANDS.get(band, ""), "AP_AUTH": WIN_AUTH.get(security, "")}
    return proc.powershell(_AP_PS, env=env, timeout=60).returncode == 0


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
