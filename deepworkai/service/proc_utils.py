"""
proc_utils.py — Safe subprocess launcher, no terminal windows ever.
All subprocess calls in this project must use run_hidden() or popen_hidden().
"""

import subprocess
import sys
import os
from pathlib import Path

_WIN = sys.platform == "win32"
_NO_WIN = subprocess.CREATE_NO_WINDOW if _WIN else 0


def run_hidden(cmd: list, cwd=None, timeout=10, **kwargs) -> subprocess.CompletedProcess:
    """Run a command with no visible terminal window. Captures output."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_NO_WIN,
        **kwargs,
    )


def popen_hidden(cmd: list, cwd=None, **kwargs) -> subprocess.Popen:
    """Spawn a background process with no visible terminal window."""
    return subprocess.Popen(
        cmd,
        cwd=cwd,
        creationflags=_NO_WIN,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )


def get_python() -> str:
    """Return pythonw.exe on Windows (no console), python on other platforms."""
    if _WIN:
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        if pythonw.exists():
            return str(pythonw)
    return sys.executable


_held = []


def single_instance(name: str) -> bool:
    """True if this process is the only holder of `name` (per Windows user session).

    Taken as the first step, before any side effects, so two copies started at the same
    instant can't both run. The lock is released automatically when the process exits.
    """
    if not _WIN:
        return True
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    h = k32.CreateMutexW(None, False, "Local\\" + name)
    if not h or ctypes.get_last_error() == 183:          # ERROR_ALREADY_EXISTS
        return False
    _held.append(h)
    return True
