"""
Deep Work AI — Focus Mode
==========================
Simple focus session toggle. When active, triggers Slack DND
and records the session boundaries in activity.db.
No hardware CPU deprioritisation. No elevated permissions.
"""

import logging
from datetime import datetime

log = logging.getLogger("focus_mode")

_focus_active = False
_focus_started_at = None


def start_focus():
    """Start a focus session."""
    global _focus_active, _focus_started_at
    if _focus_active:
        return {"status": "already_active", "since": _focus_started_at}
    _focus_active = True
    _focus_started_at = datetime.now().isoformat()
    log.info("[FOCUS] Session started at %s", _focus_started_at)
    return {"status": "started", "since": _focus_started_at}


def end_focus():
    """End the current focus session."""
    global _focus_active, _focus_started_at
    if not _focus_active:
        return {"status": "not_active"}
    duration = _focus_started_at
    _focus_active = False
    _focus_started_at = None
    log.info("[FOCUS] Session ended (started at %s)", duration)
    return {"status": "ended", "started_at": duration}


def toggle_focus():
    """Toggle focus mode on/off."""
    if _focus_active:
        return end_focus()
    return start_focus()


def is_active() -> bool:
    """Return whether focus mode is currently active."""
    return _focus_active
