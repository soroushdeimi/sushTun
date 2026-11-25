"""OS firewall lockdown: the strongest layer against a real-IP leak.

While connected with `firewall.enabled`, the OS itself drops any outbound
packet that is not on the tunnel device, to a proxy server IP, to a DNS
resolver, to loopback, or (when allow_lan) to the LAN / link-local / DHCP.
This covers the gaps the app-level layers cannot: an app crash, Xray dying,
and the moment before routes appear.

One backend per OS behind a small interface. The facade picks the backend for
the running platform; tests override `_backend` to exercise a specific one.
Failures never break the connection: install raises FirewallError (the caller
logs a WARNING and continues), and remove is idempotent and best-effort.
"""
from __future__ import annotations

import sys

from . import _firewall_linux, _firewall_macos, _firewall_windows
from ._firewall_common import FirewallError, resolver_ips  # noqa: F401  (re-exported)


def _backend_for(platform: str):
    if platform == "darwin":
        return _firewall_macos
    if platform.startswith("linux"):
        return _firewall_linux
    if platform == "win32":
        return _firewall_windows
    return None


# The backend for the running platform. Tests replace this to drive a specific
# backend on any CI machine.
_backend = _backend_for(sys.platform)


def supported() -> bool:
    return bool(_backend and _backend.supported())


def install(tun_alias: str, server_ips, allow_lan: bool) -> None:
    """Install the lockdown. Raises FirewallError if it cannot be made live."""
    if _backend is None:
        raise FirewallError("no firewall backend for this platform")
    _backend.install(tun_alias, server_ips, allow_lan)


def remove() -> list[str]:
    """Idempotent teardown. Returns warning strings (empty when clean)."""
    if _backend is None:
        return []
    return _backend.remove()


def is_active() -> bool:
    return bool(_backend and _backend.is_active())


def recover_stale() -> list[str]:
    """Undo a firewall a crashed run left behind. Called on app start and by
    the boot-restore task, so the user is never left bricked: protection while
    the app is dead lasts until the next launch or reboot task. Idempotent."""
    if _backend is None:
        return []
    return _backend.remove()


def status() -> str:
    """A short English status string for the UI (translated later)."""
    if _backend is None:
        return "not supported on this platform"
    if not _backend.supported():
        return "not supported: the required firewall tool is missing"
    return "active" if _backend.is_active() else "inactive"
