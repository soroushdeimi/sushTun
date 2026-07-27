"""Gateway mode: share the tunnel with devices on the Windows hotspot.

Windows Internet Connection Sharing (ICS) NATs a "private" adapter behind a
"public" one. Pointing the public side at the Xray TUN adapter makes every
hotspot client reach the internet through the tunnel with no client-side setup.

Driven through PowerShell rather than a COM binding so the app keeps its
stdlib-only runtime footprint.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from . import proc
from .network import TUN_NAME

IS_WIN = sys.platform == "win32"

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
