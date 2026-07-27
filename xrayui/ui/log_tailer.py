"""Follow xray.log and stream new lines to the UI."""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from .. import paths
from ..core.logtail import read_new_lines


class LogTailer(QThread):
    lines = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self._running = True

    def run(self) -> None:
        path = paths.log_file()
        pos: int | None = None
        while self._running:
            try:
                if path.exists():
                    batch, pos = read_new_lines(path, pos)
                    if batch:
                        self.lines.emit(batch)
            except OSError:
                pass
            time.sleep(0.5)

    def stop(self) -> None:
        self._running = False
        self.wait(1500)
