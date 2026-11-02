"""
Debug Control Surface
=====================
Watches for an active VS Code debug session (port 4711).
When detected: switches LCD to debug mode (Continue / Step Over / etc.).
On debug end: restores previous LCD layout.
Uses pyautogui to send keyboard shortcuts to VS Code.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

_active = False
_lock   = threading.Lock()


def _is_debug_active() -> bool:
    import socket
    # Method 1: VS Code debug adapter default port
    for port in (4711, 4712, 4713):
        try:
            s = socket.socket()
            s.settimeout(0.2)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except Exception:
            pass
    # (A PowerShell '--inspect' check used to run here every 3 s: ~1,200 hidden processes an
    # hour, and Get-Process has no CommandLine on Windows PowerShell 5.1, so it never matched.)
    return False


def _watch_loop():
    global _active
    from deepworkai.service.lcd_state import set_mode, clear_mode
    while True:
        now = _is_debug_active()
        with _lock:
            was = _active
        if now and not was:
            with _lock:
                _active = True
            set_mode("debug")
        elif not now and was:
            with _lock:
                _active = False
            clear_mode("debug")
        time.sleep(3)


DEBUG_SHORTCUTS: dict[str, str | list] = {
    "Continue":   "f5",
    "Step Over":  "f10",
    "Step Into":  "f11",
    "Step Out":   ["shift", "f11"],
    "Stop":       ["shift", "f5"],
    "Breakpoint": "f9",
}


def _editor_in_front() -> bool:
    try:
        import ctypes, psutil
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(), ctypes.byref(pid))
        return psutil.Process(pid.value).name().lower() in ("code.exe", "cursor.exe", "code - insiders.exe")
    except Exception:
        return False


def execute_debug_action(action: str) -> str:
    """Send the keyboard shortcut for a debug action to VS Code."""
    key = DEBUG_SHORTCUTS.get(action)
    if not key:
        return f"unknown action: {action}"
    if not _editor_in_front():
        return "editor not in front — keys not sent"      # never type F5/F10 into a browser
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        if isinstance(key, list):
            pyautogui.hotkey(*key)
        else:
            pyautogui.press(key)
        return f"sent {action} ({key})"
    except ImportError:
        return "pyautogui not installed — pip install pyautogui"
    except Exception as e:
        return f"failed: {e}"


def is_debug_active() -> bool:
    with _lock:
        return _active


def start_debug_watcher():
    t = threading.Thread(target=_watch_loop, daemon=True, name="DebugWatcher")
    t.start()
