"""
Deep Work AI — Activity Recorder
Tracks developer-relevant activity only. Writes to data/activity.db.
Polls every 5 seconds. Includes browser tab capture via Chrome debug API.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from deepworkai.service.proc_utils import run_hidden

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH  = DATA_DIR / "activity.db"

POLL_INTERVAL = 5   # seconds
TAB_POLL_EVERY = 5  # poll browser tabs every 5×POLL = 25 s

log = logging.getLogger("recorder")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Recorder] %(message)s",
    handlers=[logging.FileHandler(DATA_DIR / "recorder.log", encoding="utf-8")],
)

DEVELOPER_APPS = {
    "code.exe":            "VS Code",
    "cursor.exe":          "Cursor",
    "devenv.exe":          "Visual Studio",
    "pycharm64.exe":       "PyCharm",
    "rider64.exe":         "Rider",
    "webstorm64.exe":      "WebStorm",
    "idea64.exe":          "IntelliJ",
    "powershell.exe":      "PowerShell",
    "windowsterminal.exe": "Terminal",
    "cmd.exe":             "CMD",
    "wt.exe":              "Terminal",
    "brave.exe":           "Brave",
    "chrome.exe":          "Chrome",
    "msedge.exe":          "Edge",
    "firefox.exe":         "Firefox",
    "slack.exe":           "Slack",
    "postman.exe":         "Postman",
}

DEVELOPER_DOMAINS = {
    "github.com", "gitlab.com", "stackoverflow.com",
    "jira.atlassian.com", "atlassian.net", "linear.app",
    "docs.", "developer.", "api.",
    "console.aws.amazon.com", "console.cloud.google.com", "portal.azure.com",
    "localhost", "127.0.0.1",
    "npmjs.com", "pypi.org", "crates.io",
    "vercel.app", "netlify.app",
}


def setup_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            description TEXT NOT NULL,
            app         TEXT DEFAULT '',
            details     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ts   ON events(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_type ON events(event_type);
    """)
    conn.commit()
    conn.close()


def save_event(event_type: str, description: str,
               app: str = "", details: dict | None = None):
    # Privacy: scrub emails/tokens/query strings before anything hits disk.
    try:
        from deepworkai.features.workflow_intelligence import redact, PRIVATE_MODE
        description = redact(description)
        if details:
            details = {k: (redact(v) if isinstance(v, str) else v) for k, v in details.items()}
            if PRIVATE_MODE:
                details.pop("title", None)
    except Exception:
        pass
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute(
            "INSERT INTO events (timestamp, event_type, description, app, details) "
            "VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), event_type, description, app,
             json.dumps(details) if details else None),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("DB write error: %s", e)


def _foreground_window() -> dict | None:
    """The window the user is actually looking at (not the highest-CPU one)."""
    try:
        import ctypes
        import psutil
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = psutil.Process(pid.value).name().lower()
        return {"name": name, "title": buf.value}
    except Exception:
        return None


def get_active_window() -> dict | None:
    fg = _foreground_window()
    if fg is not None:
        label = DEVELOPER_APPS.get(fg["name"])
        if not label:
            return None
        return {"name": fg["name"], "label": label, "title": fg["title"]}
    try:
        ps = (
            "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} "
            "| Sort-Object CPU -Desc "
            "| Select-Object -First 1 Name,MainWindowTitle "
            "| ConvertTo-Json -Compress"
        )
        r = run_hidden(
            ["powershell", "-NonInteractive", "-NoProfile", "-Command", ps],
            timeout=4,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        data  = json.loads(r.stdout)
        name  = data.get("Name", "").lower() + ".exe"
        label = DEVELOPER_APPS.get(name)
        if not label:
            return None
        return {"name": name, "label": label, "title": data.get("MainWindowTitle", "")}
    except Exception:
        return None


def get_git_context() -> dict:
    try:
        root = run_hidden(["git", "rev-parse", "--show-toplevel"], timeout=3)
        if root.returncode != 0:
            return {}
        cwd    = root.stdout.strip()
        branch = run_hidden(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=cwd, timeout=3).stdout.strip()
        changed = run_hidden(["git", "diff", "--name-only"],
                             cwd=cwd, timeout=3).stdout.strip()
        last    = run_hidden(["git", "log", "--oneline", "-1", "--format=%s"],
                             cwd=cwd, timeout=3).stdout.strip()
        return {
            "branch":        branch,
            "changed_files": [f for f in changed.splitlines() if f][:8],
            "last_commit":   last,
            "repo":          Path(cwd).name,
        }
    except Exception:
        return {}


def get_open_browser_tabs() -> list[str]:
    """
    Read open tabs from Chromium browsers via remote debug API (port 9222).
    Only returns developer-relevant URLs.
    Requires browser launched with --remote-debugging-port=9222.
    """
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:9222/json", timeout=2) as r:
            tabs = json.loads(r.read())
        return [
            t["url"] for t in tabs
            if t.get("type") == "page"
            and any(d in t.get("url", "").lower() for d in DEVELOPER_DOMAINS)
        ][:10]
    except Exception:
        return []


def record_loop(stop_event=None):
    setup_db()
    log.info("Activity recorder started. Polling every %ds.", POLL_INTERVAL)

    last_app    = None
    last_branch = None
    last_commit = None
    tab_counter = 0

    while not (stop_event and stop_event.is_set()):
        try:
            # App switch tracking
            window = get_active_window()
            if window and window["label"] != last_app:
                last_app = window["label"]
                save_event(
                    "app_switch",
                    f"Switched to {window['label']}",
                    app=window["label"],
                    details={"title": window["title"]},
                )

            # Git branch tracking
            git = get_git_context()
            if git:
                key = f"{git.get('repo')}:{git.get('branch')}"
                if key != last_branch:
                    last_branch = key
                    save_event(
                        "git_context",
                        f"Git: {git.get('repo')} [{git.get('branch')}]",
                        app="Git",
                        details=git,
                    )

            # Commit tracking — a natural breakpoint for interruption release
            if git and git.get("last_commit"):
                if last_commit is not None and git["last_commit"] != last_commit:
                    save_event("git_commit", f"Git commit: {git['last_commit'][:80]}",
                               app="Git", details={"repo": git.get("repo"),
                                                   "branch": git.get("branch")})
                last_commit = git["last_commit"]

            # Browser tab tracking (every TAB_POLL_EVERY cycles)
            tab_counter += 1
            if tab_counter >= TAB_POLL_EVERY:
                tab_counter = 0
                tabs = get_open_browser_tabs()
                for url in tabs[:3]:
                    save_event(
                        "browser_tab",
                        f"Open: {url[:80]}",
                        app="Browser",
                        details={"url": url},
                    )

        except Exception as e:
            log.error("Poll error: %s", e)

        if stop_event:
            stop_event.wait(POLL_INTERVAL)
        else:
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    record_loop()
