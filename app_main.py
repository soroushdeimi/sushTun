"""Top-level entry point for the frozen (PyInstaller) build."""
import sys

# Bind our own C++ runtime DLLs before any Qt import (see winpreload).
from xrayui import winpreload

winpreload.preload_runtime()

from xrayui.__main__ import main  # noqa: E402


def _helper_flag() -> int | None:
    """The root launch daemon starts the installed app with `--helper`: it runs
    the password-free launcher, not the GUI, so it is handled before any
    elevation or Qt. `--uninstall-helper` is a one-shot CLI action. Both are
    macOS-only and return the exit code, or None to continue normally."""
    if sys.platform != "darwin":
        return None
    if "--helper" in sys.argv:
        from xrayui.core import macos_helper
        return macos_helper.run_helper()
    if "--uninstall-helper" in sys.argv:
        from xrayui.core import macos_helper
        macos_helper.uninstall()
        return 0
    return None


if __name__ == "__main__":
    code = _helper_flag()
    sys.exit(main() if code is None else code)
