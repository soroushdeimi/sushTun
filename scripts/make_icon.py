#!/usr/bin/env python3
"""Generate assets/icon.ico from assets/icon.png (multi-size, for the Windows exe)."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "icon.png"
DST = ROOT / "assets" / "icon.ico"


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"missing {SRC} — save the logo there first")
    img = Image.open(SRC).convert("RGBA")
    img.save(DST, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print(f"wrote {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
