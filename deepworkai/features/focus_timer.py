"""
Focus Depth Timer
=================
Counts up from 0 when a focus session starts.
Updates LCD every minute so the developer sees the cost of breaking focus.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

_started_at: float | None = None
_running    = False
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _tick():
    from deepworkai.service.lcd_state import update_focus_timer
    while True:
        with _lock:
            if not _running:
                break
            started = _started_at
        if started:
            elapsed = int((time.time() - started) / 60)
            update_focus_timer(elapsed)
        time.sleep(60)


def focus_start():
    global _started_at, _running, _thread
    with _lock:
        _started_at = time.time()
        _running    = True
    _thread = threading.Thread(target=_tick, daemon=True, name="FocusTimer")
    _thread.start()
    try:
        from deepworkai.service.lcd_state import update_focus_timer, set_mode
        update_focus_timer(0)
        set_mode("focus")
    except Exception:
        pass
    return "focus timer started"


def focus_end() -> str:
    global _running
    with _lock:
        started  = _started_at
        _running = False
    elapsed = int((time.time() - started) / 60) if started else 0
    try:
        from deepworkai.service.lcd_state import update_focus_timer, clear_mode
        update_focus_timer(0)
        clear_mode("focus")
    except Exception:
        pass
    return f"focus ended after {elapsed}m"


def get_elapsed_minutes() -> int:
    with _lock:
        if _started_at and _running:
            return int((time.time() - _started_at) / 60)
    return 0


def is_active() -> bool:
    with _lock:
        return _running
