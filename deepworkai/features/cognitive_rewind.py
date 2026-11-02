"""
Cognitive Rewind — builds a minimal, high-signal context summary
from the last N minutes of developer activity.

Shows:
  - Active git repo + branch + changed files
  - Recent terminal commands (last 5)
  - Last IDE file (from window title)
  - Last relevant browser tab (GitHub/Jira/docs/SO only)
  - Micro-journal next-step note (if one was saved)

Does NOT show:
  - Raw app-switch events
  - Productivity scores
  - Slack/Discord/social tabs
  - Generic search results
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH  = DATA_DIR / "activity.db"
JOURNAL_PATH = DATA_DIR / "next_step.txt"

DEVELOPER_DOMAINS = {
    "github.com", "gitlab.com", "stackoverflow.com",
    "atlassian.net", "jira.", "linear.app",
    "docs.", "developer.", "api.",
    "console.aws", "console.cloud.google", "portal.azure",
    "localhost", "127.0.0.1",
}


def _is_developer_url(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    return any(d in url_lower for d in DEVELOPER_DOMAINS)


def build_rewind_context(minutes: int = 15) -> dict:
    """
    Returns a structured context dict for the overlay to render.
    All fields are optional — overlay must handle missing data gracefully.
    """
    context = {
        "git": None,           # dict: repo, branch, changed_files, last_commit
        "last_ide_file": None, # str: file path from window title
        "browser_tabs": [],    # list of str: only developer-relevant URLs
        "next_step": None,     # str: from micro-journal
        "since": f"{minutes} min ago",
    }

    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()

        # Most recent git context
        c = conn.execute(
            "SELECT details FROM events WHERE event_type='git_context' "
            "AND timestamp >= ? ORDER BY timestamp DESC LIMIT 1",
            ((datetime.now() - timedelta(hours=12)).isoformat(),),   # latest, even if older than the window
        )
        row = c.fetchone()
        if row:
            context["git"] = json.loads(row[0])

        # Most recent IDE window title (extract filename from title)
        c = conn.execute(
            "SELECT description, details FROM events "
            "WHERE event_type='app_switch' AND app IN ('VS Code','Cursor','PyCharm','Rider','WebStorm','IntelliJ') "
            "AND timestamp >= ? ORDER BY timestamp DESC LIMIT 1",
            (cutoff,),
        )
        row = c.fetchone()
        if row:
            details = json.loads(row[1]) if row[1] else {}
            title = details.get("title", "")
            # "● app.py - my-repo - Visual Studio Code" → app.py
            from deepworkai.service.ide_context import parse_title
            context["last_ide_file"] = parse_title(title)[0] or None

        # Developer-relevant browser tabs
        c = conn.execute(
            "SELECT details FROM events "
            "WHERE event_type='browser_tab' AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT 10",
            (cutoff,),
        )
        for row in c.fetchall():
            details = json.loads(row[0]) if row[0] else {}
            url = details.get("url", "")
            if _is_developer_url(url):
                context["browser_tabs"].append(url)
        context["browser_tabs"] = list(dict.fromkeys(context["browser_tabs"]))[:3]  # dedupe, max 3

        conn.close()
    except Exception:
        pass

    # Next-step note from micro-journal
    if JOURNAL_PATH.exists():
        try:
            note = JOURNAL_PATH.read_text(encoding="utf-8").strip()
            if note:
                context["next_step"] = note
        except Exception:
            pass

    return context


def format_rewind_for_overlay(context: dict) -> str:
    """
    Returns a short plain-text summary for the overlay UI.
    Designed to be readable in 3-5 seconds.
    """
    lines = []

    if context.get("git"):
        g = context["git"]
        lines.append(f"📦 {g.get('repo', '?')}  [{g.get('branch', '?')}]")
        changed = g.get("changed_files", [])
        if changed:
            lines.append(f"   Changed: {', '.join(changed[:3])}")
        if g.get("last_commit"):
            lines.append(f"   Last commit: {g['last_commit'][:60]}")

    if context.get("last_ide_file"):
        lines.append(f"📄 {context['last_ide_file']}")

    if context.get("browser_tabs"):
        for tab in context["browser_tabs"][:2]:
            lines.append(f"🔗 {tab[:80]}")

    if context.get("next_step"):
        lines.append(f"➡️  {context['next_step']}")

    if not lines:
        lines.append("No recent developer activity captured.")

    return "\n".join(lines)
