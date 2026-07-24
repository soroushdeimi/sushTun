"""Manage the xray.exe process and its log file."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import paths
from . import proc


def is_xray_running() -> bool:
    out = proc.run(["tasklist", "/fi", "imagename eq xray.exe"]).stdout.lower()
    return "xray.exe" in out


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
        proc.run(["taskkill", "/f", "/im", "xray.exe", "/t"])
        self._proc = None
        if self._log is not None:
            try:
                self._log.close()
            finally:
                self._log = None
