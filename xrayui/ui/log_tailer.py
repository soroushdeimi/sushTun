"""Follow xray.log and stream new lines to the UI."""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from .. import paths


class LogTailer(QThread):
    line = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._running = True

    def run(self) -> None:
        path = paths.log_file()
        pos = 0
        while self._running:
            try:
                if path.exists():
                    with open(path, encoding="utf-8", errors="replace") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    if chunk:
                        for ln in chunk.splitlines():
                            self.line.emit(ln)
            except OSError:
                pass
            time.sleep(0.5)

    def stop(self) -> None:
        self._running = False
        self.wait(1500)
