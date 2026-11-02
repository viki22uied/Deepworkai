"""
lcd_state.py — Single source of truth for LCD button displays.
All features call functions here. Nothing writes to the LCD directly.

LCD layout (up to 9 buttons on MX Creative Console):
  [0] CI status      [1] PR count       [2] Focus timer
  [3] Queue count    [4] Branch         [5] Mode label
  [6] Meeting        [7] Radar          [8] Debug
"""

import json
import threading
from pathlib import Path

BASE_DIR   = Path(__file__).parent.parent.parent
from deepworkai.service.paths import DATA_DIR  # one data folder (installed app or repo)
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "lcd_state.json"

_lock  = threading.Lock()
_state: dict = {
    "ci":          "...",    # pass / fail / pending / unknown
    "prs":         0,
    "focus_mins":  0,
    "queue":       0,
    "branch":      "...",
    "mode":        "ready",  # ready / meeting / debug / focus
    "blocked":     False,
    "temp_text":   "",
    "temp_expire": 0,        # epoch — temp_text shown until this time
}
_mode_stack: list[str] = []


def _write():
    try:
        STATE_FILE.write_text(json.dumps(_state, indent=2))
    except Exception:
        pass


def set_mode(mode: str):
    with _lock:
        if mode not in _mode_stack:
            _mode_stack.append(mode)
        _state["mode"] = _mode_stack[-1]
        _write()


def clear_mode(mode: str):
    with _lock:
        if mode in _mode_stack:
            _mode_stack.remove(mode)
        _state["mode"] = _mode_stack[-1] if _mode_stack else "ready"
        _write()


def get_mode() -> str:
    with _lock:
        return _state.get("mode", "ready")


def set_temp_text(text: str, duration_seconds: int = 10):
    """Show a temporary override message on the LCD for N seconds."""
    import time
    with _lock:
        _state["temp_text"]   = text
        _state["temp_expire"] = time.time() + duration_seconds
        _write()


def update_radar_display(radar: dict):
    with _lock:
        _state["ci"]      = radar.get("ci", "unknown")
        _state["prs"]     = radar.get("prs", 0)
        _state["branch"]  = (radar.get("branch", "?") or "?")[:12]
        _state["blocked"] = bool(radar.get("blocked"))
        _write()


def update_focus_timer(minutes: int):
    with _lock:
        _state["focus_mins"] = minutes
        _write()


def update_queue_count(count: int):
    with _lock:
        _state["queue"] = count
        _write()


def get_button_labels() -> list[str]:
    """
    Returns up to 9 label strings — one per LCD button.
    The plugin reads this every 5 s to update the hardware display.
    """
    import time
    with _lock:
        s    = _state.copy()
        mode = s.get("mode", "ready")

        # Temporary text overrides all
        if s.get("temp_text") and time.time() < s.get("temp_expire", 0):
            line1, *rest = s["temp_text"].split("\n", 1)
            line2 = rest[0][:8] if rest else ""
            return [line1[:8], line2, "", "", "", "", "", "", ""]

        if mode == "debug":
            return ["▶ Cont", "⤵ Over", "⤴ Into",
                    "↑ Out", "⏹ Stop", "● Break",
                    "", "", ""]

        if mode == "meeting":
            mins = s.get("focus_mins", 0)
            return [f"📅{mins}m", "End Mtg", "",
                    "", "", "",
                    "", "", ""]

        # Normal / ready / focus mode
        ci_icon = {"pass": "✅ CI", "fail": "❌ CI",
                   "pending": "⏳ CI"}.get(s["ci"], "CI ..")
        pr_lbl  = f"PRs:{s['prs']}" if s["prs"] > 0 else "No PRs"
        mins    = s["focus_mins"]
        timer   = f"⏱{mins}m" if mins > 0 else "Focus"
        queue   = f"Q:{s['queue']}" if s["queue"] > 0 else "Queue"
        branch  = (s.get("branch") or "?")[:7]
        md      = mode.upper()[:6]

        return [ci_icon, pr_lbl, timer, queue, branch, md, "", "", ""]


def read_state() -> dict:
    """Read full state dict (for plugin LCD polling)."""
    with _lock:
        return _state.copy()
