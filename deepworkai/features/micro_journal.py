"""
Micro-Journal — one-line next-step notes, stored in data/next_step.txt.
The note is written from the Hub's Focus page (Resume key ×2 focuses the box)
or via JOURNAL_SAVE:<text>, and surfaced by Cognitive Rewind and Time Travel.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR     = Path(__file__).parent.parent.parent
from deepworkai.service.paths import DATA_DIR  # one data folder (installed app or repo)
DATA_DIR.mkdir(parents=True, exist_ok=True)
JOURNAL_PATH = DATA_DIR / "next_step.txt"

# Path to the standalone overlay script (next to this file)
_OVERLAY_SCRIPT = Path(__file__).parent / "_journal_overlay.py"


def save_note(text: str):
    """Save a next-step note. Overwrites previous note."""
    JOURNAL_PATH.write_text(text.strip(), encoding="utf-8")


def get_note() -> str | None:
    """Return the saved note, or None if none exists."""
    if JOURNAL_PATH.exists():
        note = JOURNAL_PATH.read_text(encoding="utf-8").strip()
        return note if note else None
    return None


def clear_note():
    """Clear the note after it has been shown."""
    try:
        JOURNAL_PATH.unlink(missing_ok=True)
    except Exception:
        pass
