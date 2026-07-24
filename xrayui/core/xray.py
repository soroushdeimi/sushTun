"""Manage the xray process and its log file."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .. import paths
from . import proc

IS_WIN = sys.platform == "win32"


def is_xray_running() -> bool:
    if IS_WIN:
        out = proc.run(["tasklist", "/fi", "imagename eq xray.exe"]).stdout.lower()
        return "xray.exe" in out
    return proc.run(["pgrep", "-x", "xray"]).returncode == 0


def _kill_all() -> None:
    if IS_WIN:
        proc.run(["taskkill", "/f", "/im", "xray.exe", "/t"])
    else:
        proc.run(["pkill", "-x", "xray"])


class XrayProcess:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._log = None

    def start(self, config_path: Path) -> None:
        self.stop()
        log_path = paths.log_file()
        self._log = open(log_path, "w", encoding="utf-8", errors="replace")
        self._proc = subprocess.Popen(
            [str(paths.xray_exe()), "run", "-c", str(config_path)],
            stdout=self._log,
            stderr=subprocess.STDOUT,
            cwd=str(paths.base_dir()),
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
