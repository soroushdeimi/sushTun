from __future__ import annotations

import sys

# Absolute imports: when frozen, this module is executed as __main__ with no
# package context, so relative imports (from . import ...) would fail.
from xrayui import elevate, paths


def main() -> int:
    if not elevate.is_admin() and elevate.relaunch_as_admin():
        return 0  # elevated instance takes over
    paths.ensure_dirs()
    from xrayui.ui.app import run
    return run(sys.argv, elevated=elevate.is_admin())


if __name__ == "__main__":
    sys.exit(main())
