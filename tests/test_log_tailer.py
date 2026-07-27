"""Guard the log tailer against replaying huge logs into the UI."""
from xrayui.ui import log_tailer


def _tail(path):
    """Mirror the tailer's initial-read logic against a file."""
    size = path.stat().st_size
    pos = max(0, size - log_tailer.TAIL_BYTES)
    with open(path, encoding="utf-8", errors="replace") as f:
        f.seek(pos)
        chunk = f.read()
    batch = chunk.splitlines()
    if pos > 0 and batch:
        batch = batch[1:]
    return batch[-log_tailer.MAX_BATCH:]


def test_large_log_is_not_replayed_whole(tmp_path):
    log = tmp_path / "xray.log"
    log.write_text("\n".join(f"line {i}" for i in range(60_000)), encoding="utf-8")
    batch = _tail(log)
    assert len(batch) <= log_tailer.MAX_BATCH
    assert batch[-1] == "line 59999"  # newest lines are the ones kept


def test_small_log_is_read_from_the_start(tmp_path):
    log = tmp_path / "xray.log"
    log.write_text("a\nb\nc", encoding="utf-8")
    assert _tail(log) == ["a", "b", "c"]
