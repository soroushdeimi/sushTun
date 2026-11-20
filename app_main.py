"""Top-level entry point for the frozen (PyInstaller) build."""
import sys

# Bind our own C++ runtime DLLs before any Qt import (see winpreload).
from xrayui import winpreload

winpreload.preload_runtime()

from xrayui.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
