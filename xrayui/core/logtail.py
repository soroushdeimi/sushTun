"""Incremental log reading, independent of any UI toolkit.

A long session grows xray.log to megabytes, so a follower must never replay
the whole file: it starts near the end and returns bounded batches.
"""
from __future__ import annotations

from pathlib import Path

TAIL_BYTES = 64 * 1024
MAX_BATCH = 500


def read_new_lines(path: Path, pos: int | None) -> tuple[list[str], int]:
    """Read lines appended since `pos`.

    `pos` of None means "first read": start `TAIL_BYTES` from the end so only
    recent context is shown. Returns the new lines and the updated offset.
    """
    size = path.stat().st_size
    if pos is None:
        start = max(0, size - TAIL_BYTES)
        drop_partial = start > 0
    elif size < pos:
        start, drop_partial = 0, False  # truncated, e.g. on reconnect
    else:
        start, drop_partial = pos, False

    if size <= start:
        return [], start

    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(start)
        chunk = f.read()
        new_pos = f.tell()

    lines = chunk.splitlines()
    if drop_partial and lines:
        lines = lines[1:]  # the seek may have landed mid-line
    return lines[-MAX_BATCH:], new_pos
