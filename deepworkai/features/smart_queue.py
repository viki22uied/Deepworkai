"""
Smart Interruption Queue
When focus is interrupted, press the Queue button instead of stopping.
Saves timestamp + note. Shows live count on LCD.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH  = DATA_DIR / "queue.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=5)
    c.execute("""CREATE TABLE IF NOT EXISTS queue (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        source    TEXT DEFAULT '',
        note      TEXT DEFAULT '',
        reviewed  INTEGER DEFAULT 0
    )""")
    c.commit()
    return c


def add_item(source: str = "", note: str = ""):
    """Add an interruption to the queue."""
    db = _conn()
    db.execute(
        "INSERT INTO queue (timestamp, source, note) VALUES (?,?,?)",
        (datetime.now().isoformat(), source, note),
    )
    db.commit()
    db.close()


def add_item_and_sync(source: str = "", note: str = "") -> int:
    """Add item and immediately push count to LCD."""
    add_item(source, note)
    count = pending_count()
    try:
        from deepworkai.service.lcd_state import update_queue_count
        update_queue_count(count)
    except Exception:
        pass
    return count


def get_pending() -> list[dict]:
    """Return all unreviewed items, oldest first."""
    db = _conn()
    rows = db.execute(
        "SELECT id, timestamp, source, note FROM queue "
        "WHERE reviewed=0 ORDER BY timestamp ASC"
    ).fetchall()
    db.close()
    return [{"id": r[0], "timestamp": r[1], "source": r[2], "note": r[3]}
            for r in rows]


def mark_reviewed(item_id: int):
    db = _conn()
    db.execute("UPDATE queue SET reviewed=1 WHERE id=?", (item_id,))
    db.commit()
    db.close()


def clear_all():
    """Delete all reviewed items."""
    db = _conn()
    db.execute("DELETE FROM queue WHERE reviewed=1")
    db.commit()
    db.close()


def clear_reviewed_and_sync():
    """Clear reviewed items and sync count to LCD."""
    clear_all()
    count = pending_count()
    try:
        from deepworkai.service.lcd_state import update_queue_count
        update_queue_count(count)
    except Exception:
        pass


def pending_count() -> int:
    db = _conn()
    count = db.execute(
        "SELECT COUNT(*) FROM queue WHERE reviewed=0"
    ).fetchone()[0]
    db.close()
    return count
