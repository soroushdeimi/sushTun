from __future__ import annotations

import sys

from . import elevate, paths


def main() -> int:
    if not elevate.is_admin() and elevate.relaunch_as_admin():
        return 0  # elevated instance takes over
    paths.ensure_dirs()
    from .ui.app import run
    return run(sys.argv, elevated=elevate.is_admin())


if __name__ == "__main__":
    sys.exit(main())
