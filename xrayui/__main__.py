from __future__ import annotations

import sys

# Absolute imports: when frozen, this module is executed as __main__ with no
# package context, so relative imports (from . import ...) would fail.
from xrayui import elevate, paths
from xrayui.core.bootrestore import is_restore_argv


def main() -> int:
    argv = sys.argv
    if is_restore_argv(argv):
        return _restore_stale_main()
    if not elevate.is_admin() and elevate.relaunch_as_admin():
        return 0  # elevated instance takes over
    paths.ensure_dirs()
    from xrayui.ui.app import run
    return run(argv, elevated=elevate.is_admin())


def _restore_stale_main() -> int:
    """Headless: undo leftover DNS/routes after a crash or power-off. No UI."""
    if not elevate.is_admin() and elevate.relaunch_as_admin():
        return 0
    paths.ensure_dirs()
    from xrayui.core.connection import recover_stale

    def log(msg: str) -> None:
        try:
            with paths.log_file().open("a", encoding="utf-8") as f:
                f.write(f"[restore-stale] {msg}\n")
        except OSError:
            pass

    recover_stale(on_step=log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
