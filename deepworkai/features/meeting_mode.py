"""
Meeting Mode
=============
One button in  → saves workspace + Slack DND + LCD timer
One button out → restores workspace + shows last note + clears DND
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DATA_DIR   = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "meeting_state.json"

_state: dict = {"active": False, "started_at": None}
_state_lock = threading.Lock()


def _write_state():
    try:
        STATE_FILE.write_text(json.dumps({
            "active":     _state["active"],
            "started_at": _state["started_at"],
        }))
    except Exception:
        pass


def _timer_loop():
    from deepworkai.service.lcd_state import update_focus_timer, set_temp_text
    while True:
        with _state_lock:
            if not _state["active"]:
                break
            started = _state["started_at"]
        elapsed_mins = int((time.time() - started) / 60)
        update_focus_timer(elapsed_mins)
        time.sleep(30)


def meeting_start() -> str:
    with _state_lock:
        if _state["active"]:
            return "already in meeting mode"

    # 1. Save workspace snapshot
    try:
        from deepworkai.service.deep_restore_core import capture_workspace, save_snapshot
        snap = capture_workspace()
        save_snapshot(snap, "meeting")
    except Exception as e:
        return f"warning: capture failed ({e}) — continuing"

    # 2. Slack DND
    try:
        from deepworkai.service import slack_integration as slack
        slack.init()
        slack.shield_on(duration_minutes=120)
    except Exception:
        pass

    # 3. State
    with _state_lock:
        _state["active"]     = True
        _state["started_at"] = time.time()
        _write_state()

    # 4. LCD mode + timer thread
    try:
        from deepworkai.service.lcd_state import set_mode, set_temp_text
        set_mode("meeting")
        set_temp_text("📅 Meeting\nStarted", duration_seconds=8)
    except Exception:
        pass

    threading.Thread(target=_timer_loop, daemon=True, name="MeetingTimer").start()
    return f"meeting started — workspace saved at {datetime.now():%H:%M}"


def meeting_end() -> str:
    with _state_lock:
        if not _state["active"]:
            return "not in meeting mode"
        started = _state["started_at"]
        _state["active"] = False
        _write_state()

    elapsed_min = int((time.time() - (started or time.time())) / 60)

    # 1. Clear Slack DND
    try:
        from deepworkai.service import slack_integration as slack
        slack.init()
        slack.shield_off()
    except Exception:
        pass

    # 2. Restore workspace
    try:
        from deepworkai.service.deep_restore_core import load_latest_snapshot, restore_workspace
        snap, ts, summary = load_latest_snapshot()
        if snap:
            threading.Thread(
                target=restore_workspace, args=(snap, ts),
                daemon=True, name="MeetingRestore"
            ).start()
    except Exception:
        pass

    # 3. Show next-step note on LCD for 15 s
    try:
        from deepworkai.features.micro_journal import get_note
        from deepworkai.service.lcd_state import set_temp_text, clear_mode, update_focus_timer
        note = get_note()
        msg  = f"Resume:\n{note[:20]}" if note else "Back!\nNo note"
        set_temp_text(msg, duration_seconds=15)
        clear_mode("meeting")
        update_focus_timer(0)
    except Exception:
        pass

    return f"meeting ended ({elapsed_min}m) — workspace restoring"


def toggle_meeting() -> str:
    with _state_lock:
        active = _state["active"]
    return meeting_end() if active else meeting_start()


def get_status() -> dict:
    with _state_lock:
        started = _state["started_at"]
        active  = _state["active"]
    elapsed = int((time.time() - started) / 60) if active and started else 0
    return {"active": active, "elapsed_minutes": elapsed}
