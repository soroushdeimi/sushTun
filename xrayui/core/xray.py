"""Manage the xray process and its log file."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .. import paths
from . import proc

IS_WIN = sys.platform == "win32"


def _own_pattern() -> str:
    """pgrep/pkill -f pattern for the xray this app launched, and no other.

    Matching the bare name `xray` hits other clients too (v2rayN, Nekoray and
    friends all ship one): connecting killed their core, and their xray made a
    crashed session look alive. Ours is the one reading our runtime config.
    """
    cfg = re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", str(paths.runtime_config()))
    return f"run -c {cfg}$"


def is_xray_running() -> bool:
    if IS_WIN:
        return bool(_own_pids())
    # Bounded: without a timeout a wedged pgrep stalls disconnect forever
    # (this runs on the disconnect worker, whose hang reads as a stuck UI).
    try:
        return proc.run(["pgrep", "-f", _own_pattern()], timeout=10).returncode == 0
    except subprocess.TimeoutExpired:
        # Unknown: assume alive, so nothing is ever torn down from under a
        # live tunnel on a loaded machine.
        return True


def _own_pids() -> list[int]:
    """PIDs of the xray processes reading our runtime config, and no others.

    Win32_Process is the only tasklist-class source that also reports what a
    process was started with, and its property names are never localised, so
    this works on a Persian or German Windows too. Matching the bare image name
    hits every other client on the machine (v2rayN, Nekoray and friends all
    ship one): disconnecting killed their core, and their xray made a crashed
    session look alive.
    """
    # Match Unicode command lines inside PowerShell. Only ASCII PIDs cross
    # the console encoding boundary (OEM and Python's locale may differ).
    script = (
        "$pattern = ' -c \"?' + [regex]::Escape($env:SUSHTUN_CONFIG) + '\"?\\s*$'; "
        'Get-CimInstance Win32_Process -Filter "Name=\'xray.exe\'" | '
        'Where-Object { $_.CommandLine -match $pattern } | '
        'ForEach-Object { $_.ProcessId }'
    )
    return [int(line) for line in proc.ps_lines(
        script, env={"SUSHTUN_CONFIG": str(paths.runtime_config())}, timeout=10)
        if line.isascii() and line.isdigit()]


def _kill_all() -> None:
    # Best-effort orphan sweep: a hung helper must neither stall disconnect
    # nor fail a connect that only wanted its own child stopped.
    try:
        if IS_WIN:
            for pid in _own_pids():
                proc.run(["taskkill", "/f", "/pid", str(pid), "/t"], timeout=10)
        else:
            proc.run(["pkill", "-f", _own_pattern()], timeout=10)
    except subprocess.TimeoutExpired:
        pass


class XrayProcess:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._log = None
        self._stopped_clean = False

    def start(self, config_path: Path) -> None:
        already_clean = self._stopped_clean
        # A retry replaces a known child from this session; the first start
        # already swept crash orphans. Disconnect still performs its sweep.
        self.stop(sweep_orphans=self._proc is None)
        # A fresh connect must still find cores left by another crashed app
        # session, even if our previous disconnect found nothing else to kill.
        if already_clean:
            _kill_all()
        log_path = paths.log_file()
        self._log = open(log_path, "w", encoding="utf-8", errors="replace")
        # Point Xray at the bundled geo data explicitly: without it a frozen
        # build can fail to resolve geoip:/geosite: rules and refuse to start.
        env = proc.child_env({"XRAY_LOCATION_ASSET": str(paths.asset_dir())})
        try:
            self._proc = subprocess.Popen(
                [str(paths.xray_exe()), "run", "-c", str(config_path)],
                stdout=self._log,
                stderr=subprocess.STDOUT,
                cwd=str(paths.base_dir()),
                env=env,
                creationflags=proc.CREATE_NO_WINDOW,
                startupinfo=proc._startupinfo(),
            )
        except OSError as exc:
            # Leave a readable reason in the log so failure doesn't show "no log output".
            try:
                self._log.write(f"Failed to start Xray: {exc}\n")
                self._log.flush()
            except OSError:
                pass
            raise

        self._stopped_clean = False

    def _record_exit(self) -> None:
        """Record the process exit code if it exited with no log output."""
        if self._proc is not None and self._log is not None:
            rc = self._proc.poll()
            if rc is not None:
                try:
                    self._log.flush()
                except OSError:
                    pass
                try:
                    log_path = paths.log_file()
                    if not log_path.exists() or not log_path.read_text(encoding="utf-8", errors="replace").strip():
                        msg = (f"Xray process exited with code {rc}\n" if rc >= 0
                               else f"Xray process killed by signal {-rc}\n")
                        self._log.write(msg)
                        self._log.flush()
                except OSError:
                    pass

    def is_running(self) -> bool:
        if self._proc is None:
            return False
        if self._proc.poll() is None:
            return True
        self._record_exit()
        return False

    def stop(self, *, sweep_orphans: bool = True) -> None:
        try:
            self._record_exit()
            if self._proc is not None:
                if self._proc.poll() is None:
                    if IS_WIN:
                        proc.run(["taskkill", "/f", "/t", "/pid", str(self._proc.pid)], timeout=5)
                    else:
                        self._proc.kill()
                    try:
                        self._proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                        try:
                            self._proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            pass  # unreapable; never stall disconnect for it
            if sweep_orphans and not self._stopped_clean:
                _kill_all()
                self._stopped_clean = True
        finally:
            self._proc = None
            if self._log is not None:
                try:
                    self._log.close()
                finally:
                    self._log = None
