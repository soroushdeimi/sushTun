"""Top-level entry point for the frozen (PyInstaller) build."""
import sys

from xrayui.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
