"""Print a version's section of CHANGELOG.md, for the release body.

    python scripts/release_notes.py 0.8.1

Both language halves are printed, marker included; the app picks one. Exits 1
when the section is missing so a release cannot go out with no notes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xrayui.core.release_notes import section_for  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: release_notes.py VERSION", file=sys.stderr)
        return 2
    version = argv[1].lstrip("v")
    body = section_for((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    if not body.strip():
        print(f"CHANGELOG.md has no section for v{version}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(body.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
