"""Windows boot-time restore for leftover DNS after a crash or power-off.

`netsh set dnsservers static` is written to the adapter and survives reboot.
Routes do not. If the PC dies while connected, Wi-Fi comes back with DNS
127.0.0.1 and nothing listening, which Windows reports as No Internet.

A SYSTEM task at startup runs `--restore-stale` so the adapter is reset
without the user opening the app. macOS gets the same from a LaunchDaemon.
"""
from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path

from . import proc

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
TASK_NAME = "sushTunBootRestore"
MAC_LABEL = "com.soroushdeimi.sushtun.bootrestore"
MAC_PLIST = Path("/Library/LaunchDaemons") / f"{MAC_LABEL}.plist"

_REGISTER_PS = """
$exe = $env:SUSH_EXE
$arg = $env:SUSH_ARG
$action = New-ScheduledTaskAction -Execute $exe -Argument $arg
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT20S'
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $env:SUSH_TASK -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
"""


def _action() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return sys.executable, "--restore-stale"
    main = Path(__file__).resolve().parent.parent.parent / "app_main.py"
    return sys.executable, f'"{main}" --restore-stale'


def _mac_program() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--restore-stale"]
    main = Path(__file__).resolve().parent.parent.parent / "app_main.py"
    return [sys.executable, str(main), "--restore-stale"]


def mac_plist_bytes() -> bytes:
    return plistlib.dumps({
        "Label": MAC_LABEL,
        "ProgramArguments": _mac_program(),
        "RunAtLoad": True,
    })


def _install_mac() -> None:
    # macOS keeps the DNS networksetup wrote across a reboot, just as Windows
    # keeps netsh's: a Mac that dies while connected comes back with DNS on
    # 127.0.0.1 and nothing answering. launchd runs every daemon in this
    # directory as root at boot, so nothing needs loading now.
    if MAC_PLIST.is_symlink():
        raise RuntimeError(f"refusing to write through a symlink at {MAC_PLIST}")
    tmp = MAC_PLIST.with_suffix(".tmp")
    tmp.write_bytes(mac_plist_bytes())
    tmp.chmod(0o644)  # launchd ignores a daemon plist others can write
    os.replace(tmp, MAC_PLIST)


def install() -> None:
    if IS_MAC:
        _install_mac()
        return
    if not IS_WIN:
        return
    exe, arg = _action()
    proc.powershell(
        _REGISTER_PS,
        env={"SUSH_EXE": exe, "SUSH_ARG": arg, "SUSH_TASK": TASK_NAME},
        timeout=30,
    )


def uninstall() -> None:
    if IS_MAC:
        MAC_PLIST.unlink(missing_ok=True)
        return
    if not IS_WIN:
        return
    proc.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])


def is_restore_argv(argv: list[str]) -> bool:
    return "--restore-stale" in argv
