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
        out = proc.run(["tasklist", "/fi", "imagename eq xray.exe"]).stdout.lower()
        return "xray.exe" in out
    return proc.run(["pgrep", "-f", _own_pattern()]).returncode == 0


def _kill_all() -> None:
    if IS_WIN:
        proc.run(["taskkill", "/f", "/im", "xray.exe", "/t"])
    else:
        proc.run(["pkill", "-f", _own_pattern()])


class XrayProcess:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._log = None

    def start(self, config_path: Path) -> None:
        self.stop()
        log_path = paths.log_file()
        self._log = open(log_path, "w", encoding="utf-8", errors="replace")
        # Point Xray at the bundled geo data explicitly: without it a frozen
        # build can fail to resolve geoip:/geosite: rules and refuse to start.
        env = proc.child_env({"XRAY_LOCATION_ASSET": str(paths.asset_dir())})
        self._proc = subprocess.Popen(
            [str(paths.xray_exe()), "run", "-c", str(config_path)],
            stdout=self._log,
            stderr=subprocess.STDOUT,
            cwd=str(paths.base_dir()),
            env=env,
            creationflags=proc.CREATE_NO_WINDOW,
            startupinfo=proc._startupinfo(),
        )

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        _kill_all()
        self._proc = None
        if self._log is not None:
            try:
                self._log.close()
            finally:
                self._log = None
