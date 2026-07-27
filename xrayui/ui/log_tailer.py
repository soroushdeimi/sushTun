"""Follow xray.log and stream new lines to the UI."""
from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from .. import paths

# Only replay recent context on startup: the log can reach megabytes in a long
# session, and pushing every historical line at the UI would freeze the app.
TAIL_BYTES = 64 * 1024
MAX_BATCH = 500


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
                    size = path.stat().st_size
                    if pos is None:
                        pos = max(0, size - TAIL_BYTES)
                        skip_partial = pos > 0
                    elif size < pos:
                        pos, skip_partial = 0, False  # truncated on reconnect
                    else:
                        skip_partial = False
                    if size > pos:
                        with open(path, encoding="utf-8", errors="replace") as f:
                            f.seek(pos)
                            chunk = f.read()
                            pos = f.tell()
                        batch = chunk.splitlines()
                        if skip_partial and batch:
                            batch = batch[1:]  # seek may land mid-line
                        if batch:
                            self.lines.emit(batch[-MAX_BATCH:])
            except OSError:
                pass
            time.sleep(0.5)

    def stop(self) -> None:
        self._running = False
        self.wait(1500)
