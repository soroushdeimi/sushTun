"""Start sushTun automatically at login.

Each platform needs a different mechanism, so each is handled entirely
separately. Linux only supports the installed .deb (paths.installed()):
the portable build has no fixed path a polkit rule or autostart entry
could name without granting root to whatever happens to be at that path
later -- a much broader hole than this feature is worth.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import paths
from . import proc

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

TASK_NAME = "sushTunAutostart"

# Matches scripts/build_deb.py's PREFIX/EXE/POLICY_ID exactly -- the .deb is
# the only Linux install this targets, so the path is fixed by definition.
_PREFIX = "/opt/sushtun"
_EXE = f"{_PREFIX}/sushtun"
POLICY_ID = "io.github.soroushdeimi.sushtun"
POLKIT_RULE = Path("/etc/polkit-1/rules.d/49-sushtun.rules")


def _real_user() -> str | None:
    """The user pkexec/sudo elevated *from*, never root itself."""
    uid = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    if not uid:
        return None
    import pwd
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (ValueError, KeyError):
        return None


def _desktop_file(user: str) -> Path:
    import pwd
    home = Path(pwd.getpwnam(user).pw_dir)
    return home / ".config" / "autostart" / "sushtun.desktop"


def polkit_rule_text(user: str) -> str:
    # Scoped to exactly our own action id, this one user, and only while
    # they're the active local session -- never org.freedesktop.policykit.
    # exec, which would grant running arbitrary commands as root.
    return (
        "polkit.addRule(function(action, subject) {\n"
        f'    if (action.id == "{POLICY_ID}" && subject.user == "{user}" '
        "&& subject.local && subject.active) {\n"
        "        return polkit.Result.YES;\n"
        "    }\n"
        "});\n"
    )


def _desktop_file_text() -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=sushTun\n"
        f"Exec={_EXE} --autostart\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def is_supported() -> tuple[bool, str]:
    if IS_MAC:
        return False, "Not supported on macOS yet."
    if IS_WIN:
        return True, ""
    if not paths.installed():
        return False, "Install the .deb package to start sushTun at login."
    if _real_user() is None:
        return False, "Can't tell which user to start sushTun for."
    return True, ""


def enable() -> None:
    ok, reason = is_supported()
    if not ok:
        raise RuntimeError(reason)
    if IS_WIN:
        _enable_windows()
    else:
        _enable_linux()


def disable() -> None:
    if IS_WIN:
        _disable_windows()
    elif not IS_MAC:
        _disable_linux()


def _enable_linux() -> None:
    user = _real_user()
    if user is None:
        raise RuntimeError("Can't tell which user to start sushTun for.")
    import pwd
    pw = pwd.getpwnam(user)

    POLKIT_RULE.parent.mkdir(parents=True, exist_ok=True)
    POLKIT_RULE.write_text(polkit_rule_text(user), encoding="utf-8")
    POLKIT_RULE.chmod(0o644)

    desktop = _desktop_file(user)
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(_desktop_file_text(), encoding="utf-8")
    desktop.chmod(0o644)
    # Written as root (via pkexec); hand it back to the real user so their
    # own session can read and later remove it.
    os.chown(desktop.parent.parent, pw.pw_uid, pw.pw_gid)  # ~/.config
    os.chown(desktop.parent, pw.pw_uid, pw.pw_gid)  # ~/.config/autostart
    os.chown(desktop, pw.pw_uid, pw.pw_gid)


def _disable_linux() -> None:
    POLKIT_RULE.unlink(missing_ok=True)
    user = _real_user()
    if user is not None:
        _desktop_file(user).unlink(missing_ok=True)


_REGISTER_PS = """
$exe = $env:SUSH_EXE
$arg = $env:SUSH_ARG
$action = New-ScheduledTaskAction -Execute $exe -Argument $arg
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $env:SUSH_TASK -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
"""


def _action() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return sys.executable, "--autostart"
    main = Path(__file__).resolve().parent.parent.parent / "app_main.py"
    return sys.executable, f'"{main}" --autostart'


def _enable_windows() -> None:
    exe, arg = _action()
    proc.powershell(
        _REGISTER_PS,
        env={"SUSH_EXE": exe, "SUSH_ARG": arg, "SUSH_TASK": TASK_NAME},
        timeout=30,
    )


def _disable_windows() -> None:
    proc.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
