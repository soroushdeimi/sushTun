"""Follow xray.log and stream new lines to the UI."""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from .. import paths
from ..core.logtail import read_new_lines


class LogTailer(QThread):
    lines = Signal(list)
    INTERVAL = 0.5
    # While the window is hidden: lines still arrive, just in larger batches,
    # and the thread wakes four times less often.
    IDLE_INTERVAL = 2.0

    def __init__(self) -> None:
        super().__init__()
        self._running = True
        self.interval = self.INTERVAL

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
            time.sleep(self.interval)

    def stop(self) -> None:
        self._running = False
        self.wait(1500)
