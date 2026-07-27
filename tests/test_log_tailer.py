"""Guard the log follower against replaying huge logs into the UI."""
from xrayui.core.logtail import MAX_BATCH, read_new_lines


def test_large_log_is_not_replayed_whole(tmp_path):
    log = tmp_path / "xray.log"
    log.write_text("\n".join(f"line {i}" for i in range(60_000)), encoding="utf-8")
    batch, pos = read_new_lines(log, None)
    assert len(batch) <= MAX_BATCH
    assert batch[-1] == "line 59999"  # newest lines are the ones kept
    assert pos == log.stat().st_size


def test_small_log_is_read_from_the_start(tmp_path):
    log = tmp_path / "xray.log"
    log.write_text("a\nb\nc", encoding="utf-8")
    assert read_new_lines(log, None)[0] == ["a", "b", "c"]


def test_only_appended_lines_are_returned(tmp_path):
    log = tmp_path / "xray.log"
    log.write_text("a\nb\n", encoding="utf-8")
    _, pos = read_new_lines(log, None)
    with open(log, "a", encoding="utf-8") as f:
        f.write("c\n")
    batch, _ = read_new_lines(log, pos)
    assert batch == ["c"]


def test_truncation_restarts_from_the_beginning(tmp_path):
    log = tmp_path / "xray.log"
    log.write_text("old content here\n", encoding="utf-8")
    _, pos = read_new_lines(log, None)
    log.write_text("fresh\n", encoding="utf-8")  # reconnect truncates the log
    batch, _ = read_new_lines(log, pos)
    assert batch == ["fresh"]
