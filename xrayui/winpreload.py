"""Load our own C++ runtime DLLs by full path before any Qt import.

Windows keeps one module per DLL base name; a security product (e.g. McAfee)
may have injected its own msvcp140.dll, and a later LoadLibrary("msvcp140.dll")
would then be bound to that copy. Binding our copies first avoids that.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Order matters: vcruntime first, then the msvcp family, then concrt.
_RUNTIME_DLLS = (
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "concrt140.dll",
)


def preload_runtime(base=None) -> list[str]:
    """Load the C++ runtime DLLs from base by full path. Returns the names
    that loaded, lower-case. No-op ([]) off win32 or when not frozen."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return []
    if base is None:
        base = Path(sys._MEIPASS)
    base = Path(base)
    # Case-insensitive match: the bundle has MSVCP140_1.dll upper-case on disk.
    try:
        by_name = {p.name.lower(): p for p in base.iterdir() if p.is_file()}
    except OSError:
        by_name = {}
    loaded: list[str] = []
    try:
        import ctypes
    except ImportError:
        return []
    for name in _RUNTIME_DLLS:
        full = by_name.get(name)
        if full is None:
            continue
        try:
            ctypes.WinDLL(str(full))
        except OSError:
            continue
        loaded.append(name)
    try:
        os.add_dll_directory(str(base))
    except (OSError, AttributeError):
        pass
    return loaded
