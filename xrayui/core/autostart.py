"""Start sushTun automatically at login.

Each platform needs a different mechanism, so each is handled entirely
separately. Linux only supports the installed .deb (paths.installed()):
the portable build has no fixed path a polkit rule or autostart entry
could name without granting root to whatever happens to be at that path
later -- a much broader hole than this feature is worth.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .. import paths
from . import proc, userfs

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


_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")


def polkit_rule_text(user: str) -> str:
    # Scoped to exactly our own action id, this one user, and only while
    # they're the active local session -- never org.freedesktop.policykit.
    # exec, which would grant running arbitrary commands as root. The
    # username comes from pwd (the system's own account database), but
    # it's still interpolated into a JS literal: validate the character
    # set and use json.dumps for the actual quoting/escaping rather than
    # trusting a raw f-string to be safe against a crafted account name.
    if not _USERNAME_RE.match(user):
        raise ValueError(f"unexpected user name for the login rule: {user!r}")
    return (
        "polkit.addRule(function(action, subject) {\n"
        f'    if (action.id == "{POLICY_ID}" && subject.user == {json.dumps(user)} '
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


def _write_polkit_rule(user: str) -> None:
    # /etc/polkit-1/rules.d is root-owned, so this part legitimately stays
    # a root write -- but still atomic (tmp + os.replace) and refusing to
    # write through a pre-existing symlink at the rule's own path.
    POLKIT_RULE.parent.mkdir(parents=True, exist_ok=True)
    if POLKIT_RULE.is_symlink():
        raise RuntimeError(f"refusing to write through a symlink at {POLKIT_RULE}")
    tmp = POLKIT_RULE.with_suffix(".tmp")
    tmp.write_text(polkit_rule_text(user), encoding="utf-8")
    tmp.chmod(0o644)
    os.replace(tmp, POLKIT_RULE)


def _enable_linux() -> None:
    user = _real_user()
    if user is None:
        raise RuntimeError("Can't tell which user to start sushTun for.")
    import pwd
    pw = pwd.getpwnam(user)

    _write_polkit_rule(user)

    # ~/.config/autostart is entirely user-controlled: a local user could
    # have pre-planted it (or the .desktop file itself) as a symlink to a
    # root-owned file. Writing it as that user, not as root, means such a
    # symlink can only ever be followed to wherever the user could already
    # write themselves -- so no chown is needed, or safe, afterwards.
    desktop = _desktop_file(user)
    userfs.write_as_user(desktop, _desktop_file_text().encode("utf-8"), pw.pw_uid, pw.pw_gid)


def _disable_linux() -> None:
    POLKIT_RULE.unlink(missing_ok=True)
    user = _real_user()
    if user is not None:
        import pwd
        pw = pwd.getpwnam(user)
        userfs.unlink_as_user(_desktop_file(user), pw.pw_uid, pw.pw_gid)


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
    # $env:USERNAME is the standard user who launched sushTun, not whoever
    # supplied the UAC credentials -- but "over-the-shoulder" UAC (a
    # standard user elevating with a different admin's password) still
    # registers the task for the standard user's own session, which is
    # what New-ScheduledTaskPrincipal -UserId actually names. A known,
    # accepted limitation, not something this fixes.
    exe, arg = _action()
    proc.powershell(
        _REGISTER_PS,
        env={"SUSH_EXE": exe, "SUSH_ARG": arg, "SUSH_TASK": TASK_NAME},
        timeout=30,
    )


def _disable_windows() -> None:
    proc.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
