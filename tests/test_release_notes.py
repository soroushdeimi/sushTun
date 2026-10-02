"""Release notes: the CHANGELOG is the source, shown in the reader's language."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from xrayui import __version__
from xrayui.core import release_notes

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

SAMPLE = """# Changelog

## v0.3.0 — thing

- three

<!-- fa -->
- سه

## v0.2.0

- two

## v0.1.0

- one
"""


def test_section_for_a_middle_section_stops_at_the_next_version():
    body = release_notes.section_for(SAMPLE, "0.2.0")
    assert body.strip() == "- two"


def test_section_for_the_last_section_runs_to_the_end():
    assert release_notes.section_for(SAMPLE, "0.1.0").strip() == "- one"


def test_section_for_a_heading_with_a_suffix_leaves_the_heading_out():
    body = release_notes.section_for(SAMPLE, "0.3.0")
    assert "thing" not in body and "- three" in body and "- سه" in body


def test_section_for_a_missing_version_is_empty():
    assert release_notes.section_for(SAMPLE, "9.9.9") == ""


def test_section_for_does_not_match_a_longer_version():
    assert release_notes.section_for("## v0.10.0\n\n- x\n", "0.1.0") == ""


def test_pick_language_prefers_the_persian_half_for_fa():
    notes = "- three\n\n<!-- fa -->\n- سه\n"
    assert release_notes.pick_language(notes, "fa").strip() == "- سه"
    assert release_notes.pick_language(notes, "en").strip() == "- three"


def test_pick_language_falls_back_to_english_without_a_persian_half():
    assert release_notes.pick_language("- three\n", "fa").strip() == "- three"


def test_pick_language_ignores_an_empty_persian_half():
    assert release_notes.pick_language("- three\n<!-- fa -->\n  \n", "fa").strip() == "- three"


def test_clean_drops_githubs_generated_lines():
    raw = ("## What's Changed\n"
           "* Fix a thing by @someone in https://github.com/x/y/pull/3\n"
           "- a real note\n\n"
           "**Full Changelog**: https://github.com/x/y/compare/v1...v2\n")
    assert release_notes.clean(raw) == "- a real note"


def test_clean_of_only_generated_text_is_empty():
    assert release_notes.clean(
        "**Full Changelog**: https://github.com/x/y/compare/v1...v2") == ""


def test_the_real_changelog_has_both_languages_for_the_recent_versions():
    for version in ("0.8.0", "0.8.1"):
        body = release_notes.section_for(CHANGELOG, version)
        assert release_notes.pick_language(body, "en").strip(), version
        fa = release_notes.pick_language(body, "fa")
        assert fa != release_notes.pick_language(body, "en") and fa.strip(), version
        assert re.search(r"[؀-ۿ]", fa), version


def test_the_current_version_has_notes():
    assert release_notes.section_for(CHANGELOG, __version__).strip()


def test_the_script_prints_the_section_and_fails_when_it_is_missing():
    script = ROOT / "scripts" / "release_notes.py"
    ok = subprocess.run([sys.executable, str(script), "0.8.1"], capture_output=True,
                        text=True, encoding="utf-8", cwd=ROOT)
    assert ok.returncode == 0 and "<!-- fa -->" in ok.stdout
    bad = subprocess.run([sys.executable, str(script), "99.0.0"], capture_output=True,
                         text=True, encoding="utf-8", cwd=ROOT)
    assert bad.returncode == 1


def test_the_release_workflow_publishes_the_written_notes():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "body_path: release_notes.md" in text
    assert "generate_release_notes" not in text
    assert "scripts/release_notes.py" in text
