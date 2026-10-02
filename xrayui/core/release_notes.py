"""Release notes: CHANGELOG.md is the source, the update window the reader.

A version's section is the English notes, optionally followed by `<!-- fa -->`
and the same notes in Persian. GitHub's own generated text (a bare compare
link, a list of pull requests) is not notes and is dropped before display.
"""
from __future__ import annotations

import re

FA_MARKER = "<!-- fa -->"

_GENERATED = re.compile(
    r"^\s*(\*\*Full Changelog\*\*:.*|#+\s*What's Changed\s*|\*\s.*\sby\s@\S+\sin\s+https?://\S+\s*)$",
    re.MULTILINE)


def section_for(changelog_text: str, version: str) -> str:
    """The body of `## v<version>` up to the next `## v`, heading left out."""
    heading = re.compile(rf"^## v{re.escape(version)}(?!\S).*$", re.MULTILINE)
    match = heading.search(changelog_text)
    if not match:
        return ""
    rest = changelog_text[match.end():]
    nxt = re.search(r"^## v", rest, re.MULTILINE)
    return (rest[:nxt.start()] if nxt else rest).strip("\n") + "\n"


def pick_language(notes: str, lang: str) -> str:
    english, _, persian = notes.partition(FA_MARKER)
    if lang == "fa" and persian.strip():
        return persian
    return english


def clean(notes: str) -> str:
    return _GENERATED.sub("", notes).strip()


_TOKEN = r"[`+\-./_:@#]*[A-Za-z0-9][`A-Za-z0-9+\-./_:@#]*"
_SKIP_OR_RUN = re.compile(
    rf"(\]\([^)]*\)|<?https?://\S+)|({_TOKEN}(?: +(?:[+/&] +)?{_TOKEN})*)")
_MARKER = re.compile(r"^(\s*(?:[-*+]|\d+\.|#+)\s+)?(.*)$", re.DOTALL)
_LRI, _PDI = "\u2066", "\u2069"


def _wrap(match: re.Match) -> str:
    if match.group(1):
        return match.group(1)
    run = match.group(2)
    tail = re.search(r"[^A-Za-z0-9`]*$", run).group()
    return f"{_LRI}{run[:len(run) - len(tail)]}{_PDI}{tail}"


def isolate_latin(text: str) -> str:
    """Wrap each run of Latin-script text in an LTR isolate so it keeps its
    order inside a right-to-left line. List markers, headings and link targets
    are left alone: they are Markdown, not text."""
    out = []
    for line in text.split("\n"):
        marker, rest = _MARKER.match(line).groups()
        lead = re.match(r"\s*", rest).end()
        first = _SKIP_OR_RUN.match(rest, lead)
        start = first.end() if first and first.group(2) else 0
        out.append((marker or "") + rest[:start] + _SKIP_OR_RUN.sub(_wrap, rest[start:]))
    return "\n".join(out)
