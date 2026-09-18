"""The packaged build must carry every non-Python file the UI loads by path."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_build_spec_bundles_every_ui_data_file():
    spec = (ROOT / "tools" / "build.spec").read_text(encoding="utf-8")
    ui = ROOT / "xrayui" / "ui"
    suffixes = {p.suffix for p in ui.iterdir() if p.is_file() and p.suffix not in {".py", ".pyc"}}
    assert suffixes, "expected at least the checkbox glyph (.svg)"
    for suffix in suffixes:
        # A glob per suffix; a new data file type needs its own line in the spec.
        assert f'glob("*{suffix}")' in spec, f"build.spec does not bundle xrayui/ui/*{suffix}"
