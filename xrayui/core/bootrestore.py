"""Windows boot-time restore for leftover DNS after a crash or power-off.

`netsh set dnsservers static` is written to the adapter and survives reboot.
Routes do not. If the PC dies while connected, Wi-Fi comes back with DNS
127.0.0.1 and nothing listening, which Windows reports as No Internet.

A SYSTEM task at startup runs `--restore-stale` so the adapter is reset
without the user opening the app.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import proc

IS_WIN = sys.platform == "win32"
TASK_NAME = "sushTunBootRestore"

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


def install() -> None:
    if not IS_WIN:
        return
    exe, arg = _action()
    proc.powershell(
        _REGISTER_PS,
        env={"SUSH_EXE": exe, "SUSH_ARG": arg, "SUSH_TASK": TASK_NAME},
        timeout=30,
    )


def uninstall() -> None:
    if not IS_WIN:
        return
    proc.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])


def is_restore_argv(argv: list[str]) -> bool:
    return "--restore-stale" in argv
