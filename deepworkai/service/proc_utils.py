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
