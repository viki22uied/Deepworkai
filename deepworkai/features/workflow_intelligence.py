"""
Deep Work AI — Workflow Intelligence (fully local)
===================================================
Turns the raw activity stream (data/activity.db, written by the activity
recorder) into an understanding of *what you are doing* and *how deep you are*,
then uses that to:

  1. Understand workflows  — infer the current activity (coding, debugging,
     reviewing, researching, communicating, meeting) and a 0-100 focus-depth
     score from app usage, window titles, switch rate and dwell time.
  2. Auto-capture context  — when you drop out of a deep state into an
     interruption (e.g. Slack/Teams/mail after 15+ min of focus), save a
     context anchor + snapshot automatically so you can resume later.
  3. Manage interruptions  — decide per notification whether to DELIVER now,
     HOLD until a natural breakpoint, or BATCH into a digest, using the
     classifier priority, the current focus depth, and learned sender weight.
     Held items are released automatically at breakpoints (commit, branch
     switch, leaving the IDE, end of a deep block).

Privacy guarantees:
  * No network calls. No cloud models. Everything is stdlib + local SQLite.
  * Window titles and notification text are passed through `redact()` before
    storage (emails, URLs' query strings, tokens/keys, long digit runs).
  * Data retention: intelligence tables are purged after RETENTION_DAYS.
  * DEEPWORKAI_PRIVATE_MODE=1 disables auto-capture and title storage.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
ACTIVITY_DB = DATA_DIR / "activity.db"
INTEL_DB    = DATA_DIR / "intelligence.db"

log = logging.getLogger("workflow_intelligence")

# ── Tunables ──────────────────────────────────────────────────────────────────
WINDOW_MINUTES        = 20     # look-back window for state inference
DEEP_THRESHOLD        = 60     # focus score ≥ this = "deep"
AUTO_CAPTURE_MIN_DEEP = 15     # minutes of deep work before auto-capture is worth it
AUTO_CAPTURE_COOLDOWN = 600    # seconds between auto-captures
TICK_SECONDS          = 30
RETENTION_DAYS        = int(os.environ.get("DEEPWORKAI_RETENTION_DAYS", "14"))

PRIVATE_MODE = os.environ.get("DEEPWORKAI_PRIVATE_MODE", "0") == "1"

DELIVER, HOLD, BATCH = "DELIVER", "HOLD", "BATCH"

# ── Privacy: redaction ───────────────────────────────────────────────────────
_REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|"
                r"sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"), "<secret>"),
    (re.compile(r"(?i)\b(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*\S+"), r"\1=<secret>"),
    (re.compile(r"(https?://[^\s?#]+)[?#]\S*"), r"\1"),          # strip query strings
    (re.compile(r"\b\d{9,}\b"), "<num>"),                       # card/phone/account numbers
]


def redact(text: str) -> str:
    if not text:
        return ""
    for pat, repl in _REDACTIONS:
        text = pat.sub(repl, text)
    return text[:300]


# ── Workflow understanding ───────────────────────────────────────────────────
IDE_APPS      = {"VS Code", "Cursor", "Visual Studio", "PyCharm", "Rider", "WebStorm", "IntelliJ"}
TERMINAL_APPS = {"PowerShell", "Terminal", "CMD"}
BROWSER_APPS  = {"Chrome", "Edge", "Brave", "Firefox", "Browser"}
CHAT_APPS     = {"Slack", "Teams", "Outlook", "Discord"}
MEETING_HINTS = re.compile(r"(?i)\b(zoom|meet\.google|teams meeting|webex|huddle|call with)\b")

_ACTIVITY_SIGNALS: dict[str, list[tuple[re.Pattern, float]]] = {
    "debugging": [
        (re.compile(r"(?i)\b(debug|breakpoint|traceback|exception|stack ?trace|error|failing|pytest|jest)\b"), 2.0),
    ],
    "reviewing": [
        (re.compile(r"(?i)(pull request|/pull/|merge request|review|diff|compare)"), 2.0),
    ],
    "researching": [
        (re.compile(r"(?i)(stackoverflow|docs\.|developer\.|documentation|api reference|readme|mdn)"), 1.5),
    ],
    "coding": [
        (re.compile(r"\.(py|js|ts|tsx|jsx|go|rs|java|cs|cpp|c|rb|kt|swift)\b"), 1.5),
    ],
}


@dataclass
class WorkflowState:
    activity: str = "idle"          # coding|debugging|reviewing|researching|communicating|meeting|idle
    focus_score: int = 0            # 0-100
    deep: bool = False
    deep_minutes: int = 0           # length of current uninterrupted dev streak
    switches_per_10m: float = 0.0
    dev_share: float = 0.0          # fraction of time in IDE/terminal/dev browser
    top_app: str = ""
    repo: str = ""
    branch: str = ""
    signals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_ts(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now()


def load_recent_events(minutes: int = WINDOW_MINUTES, db: Path = ACTIVITY_DB) -> list[dict]:
    if not db.exists():
        return []
    since = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    try:
        conn = sqlite3.connect(db, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT timestamp, event_type, description, app, details FROM events "
            "WHERE timestamp >= ? ORDER BY timestamp ASC", (since,)
        ).fetchall()
        # Git context is only logged when it changes — carry the latest one into
        # the window so repo/branch don't vanish 20 minutes after a checkout.
        last_git = conn.execute(
            "SELECT timestamp, event_type, description, app, details FROM events "
            "WHERE event_type='git_context' AND timestamp < ? ORDER BY timestamp DESC LIMIT 1",
            (since,)).fetchone()
        if last_git and not any(r["event_type"] == "git_context" for r in rows):
            rows = [last_git] + list(rows)
        conn.close()
    except Exception as e:
        log.debug("activity read failed: %s", e)
        return []
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d["details"]) if d["details"] else {}
        except Exception:
            d["details"] = {}
        out.append(d)
    return out


def infer_state(events: list[dict], now: datetime | None = None,
                window_minutes: int = WINDOW_MINUTES) -> WorkflowState:
    """Pure function: activity events → WorkflowState. Easy to unit-test."""
    now = now or datetime.now()
    st = WorkflowState()
    switches = [e for e in events if e["event_type"] == "app_switch"]
    if not events:
        return st

    # Dwell time per app: time from each switch until the next one (or now).
    dwell: Counter = Counter()
    for i, e in enumerate(switches):
        start = _parse_ts(e["timestamp"])
        end = _parse_ts(switches[i + 1]["timestamp"]) if i + 1 < len(switches) else now
        dwell[e["app"]] += max(0.0, (end - start).total_seconds())
    total = sum(dwell.values()) or 1.0

    # Text evidence (titles, urls) for activity classification.
    scores: Counter = Counter()
    for e in events:
        text = " ".join([e.get("description", ""), json.dumps(e.get("details") or {})])
        weight = 1.0
        if e["event_type"] == "app_switch" and switches and e is switches[-1]:
            weight = 4.0                                   # current window matters most
        for act, pats in _ACTIVITY_SIGNALS.items():
            for pat, w in pats:
                if pat.search(text):
                    scores[act] += w * weight
        if MEETING_HINTS.search(text):
            scores["meeting"] += 3.0 * weight
        if e["event_type"] == "git_context":
            st.repo = e["details"].get("repo", st.repo)
            st.branch = e["details"].get("branch", st.branch)

    ide_t   = sum(v for k, v in dwell.items() if k in IDE_APPS)
    term_t  = sum(v for k, v in dwell.items() if k in TERMINAL_APPS)
    brow_t  = sum(v for k, v in dwell.items() if k in BROWSER_APPS)
    chat_t  = sum(v for k, v in dwell.items() if k in CHAT_APPS)
    scores["coding"]        += 3.0 * (ide_t + term_t) / total
    scores["communicating"] += 5.0 * chat_t / total
    scores["researching"]   += 1.0 * brow_t / total

    st.top_app = dwell.most_common(1)[0][0] if dwell else (switches[-1]["app"] if switches else "")
    current = switches[-1]["app"] if switches else ""
    if current in CHAT_APPS:
        scores["communicating"] += 5.0

    st.activity = scores.most_common(1)[0][0] if scores else "idle"
    st.signals = {k: round(v, 2) for k, v in scores.most_common()}

    # Focus score: dev share, low switch rate, long current streak.
    span_min = max(1.0, min(window_minutes,
                            (now - _parse_ts(events[0]["timestamp"])).total_seconds() / 60))
    st.switches_per_10m = round(len(switches) / span_min * 10, 1)
    st.dev_share = round((ide_t + term_t + 0.5 * brow_t) / total, 2)

    streak_start = None
    for e in reversed(switches):
        if e["app"] in IDE_APPS | TERMINAL_APPS | BROWSER_APPS:
            streak_start = _parse_ts(e["timestamp"])
        else:
            break
    st.deep_minutes = int((now - streak_start).total_seconds() // 60) if streak_start else 0

    # ~1 when calm, →0 when frantic. Exponent clamped: a burst of switches overflowed exp().
    switch_penalty = 1.0 / (1.0 + math.exp(min(50.0, st.switches_per_10m - 6)))
    streak_bonus   = min(1.0, st.deep_minutes / 25.0)
    score = 100 * (0.45 * st.dev_share + 0.30 * switch_penalty + 0.25 * streak_bonus)
    if st.activity in ("communicating", "meeting"):
        score *= 0.5
    st.focus_score = int(round(max(0, min(100, score))))
    st.deep = st.focus_score >= DEEP_THRESHOLD
    return st


# ── Intelligence DB (local) ──────────────────────────────────────────────────
_schema_ready: set = set()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(INTEL_DB, timeout=10)
    key = str(INTEL_DB)
    if key not in _schema_ready:              # create tables once per process, not per call
        conn.execute("PRAGMA journal_mode=WAL")   # readers never block the writer
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS state_log (
                ts TEXT NOT NULL, activity TEXT, focus_score INTEGER, deep INTEGER
            );
            CREATE TABLE IF NOT EXISTS auto_context (
                ts TEXT NOT NULL, reason TEXT, activity TEXT, repo TEXT, branch TEXT,
                anchor TEXT, summary TEXT
            );
            CREATE TABLE IF NOT EXISTS decisions (
                ts TEXT NOT NULL, notif_id TEXT, source TEXT, sender TEXT, priority TEXT,
                decision TEXT, focus_score INTEGER, released INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sender_weight (
                sender TEXT PRIMARY KEY, opened INTEGER DEFAULT 0, ignored INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_state_ts ON state_log(ts);
            CREATE INDEX IF NOT EXISTS idx_dec_rel ON decisions(released, decision);
            CREATE INDEX IF NOT EXISTS idx_dec_ts ON decisions(ts);
            CREATE INDEX IF NOT EXISTS idx_ctx_ts ON auto_context(ts);
        """)
        _schema_ready.add(key)
    return conn


def purge_old(days: int = RETENTION_DAYS):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    try:
        with _conn() as c:
            for t in ("state_log", "auto_context", "decisions"):
                c.execute(f"DELETE FROM {t} WHERE ts < ?", (cutoff,))  # nosec B608 - fixed table names
        if ACTIVITY_DB.exists():
            with sqlite3.connect(ACTIVITY_DB, timeout=5) as c:
                c.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        notif_db = DATA_DIR / "notifications.db"
        if notif_db.exists():                       # message bodies don't live forever either
            with sqlite3.connect(notif_db, timeout=5) as c:
                c.execute("DELETE FROM notifications WHERE arrived_at < ?", (cutoff,))
    except Exception as e:
        log.debug("purge failed: %s", e)


# ── Interruption management ──────────────────────────────────────────────────
def _sender_bias(sender: str) -> float:
    """Learned importance of a sender in [-1, 1] from how you respond to them."""
    if not sender:
        return 0.0
    try:
        with _conn() as c:
            row = c.execute("SELECT opened, ignored FROM sender_weight WHERE sender=?",
                            (sender.lower(),)).fetchone()
    except Exception:
        return 0.0
    if not row:
        return 0.0
    opened, ignored = row
    return (opened - ignored) / (opened + ignored + 2)     # Laplace-smoothed


def record_feedback(sender: str, opened: bool):
    """Call when the user opens (or dismisses unread) a notification from `sender`."""
    if not sender:
        return
    col = "opened" if opened else "ignored"
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO sender_weight(sender) VALUES (?)", (sender.lower(),))
        c.execute(f"UPDATE sender_weight SET {col} = {col} + 1 WHERE sender=?",  # nosec B608 - col is one
                  (sender.lower(),))                                            # of two literals


def decide(priority: str, confidence: float, state: WorkflowState,
           sender_bias: float = 0.0, shield_active: bool = False) -> str:
    """
    Interruption cost vs. urgency.
      urgency ∈ [0,1]: classifier priority × confidence, nudged by learned sender bias.
      cost    ∈ [0,1]: how much an interruption right now would hurt.
    """
    base = {"HIGH": 0.85, "MEDIUM": 0.5, "LOW": 0.15}.get(priority, 0.5)
    urgency = base * (0.6 + 0.4 * confidence) + 0.2 * sender_bias
    cost = state.focus_score / 100.0
    if shield_active:
        cost = max(cost, 0.8)
    if state.activity == "meeting":
        cost = max(cost, 0.9)
    if state.activity == "debugging":
        cost = min(1.0, cost + 0.1)                        # debugging state is fragile

    if priority == "HIGH" and urgency >= 0.75:
        return DELIVER                                     # incidents always get through
    if urgency > cost + 0.15:
        return DELIVER
    if priority == "LOW" or urgency < 0.3:
        return BATCH
    return HOLD


def route_notification(notif: dict, shield_active: bool = False,
                       state: WorkflowState | None = None) -> str:
    """Decide + log. `notif` is a Notification.to_dict()."""
    state = state or current_state()
    sender = notif.get("sender", "")
    d = decide(notif.get("priority", "MEDIUM"), float(notif.get("confidence", 0.5)),
               state, _sender_bias(sender), shield_active)
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO decisions(ts, notif_id, source, sender, priority, decision, focus_score, released) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(), notif.get("id", ""), notif.get("source", ""),
                 redact(sender), notif.get("priority", ""), d, state.focus_score,
                 1 if d == DELIVER else 0),
            )
    except Exception as e:
        log.debug("decision log failed: %s", e)
    return d


def pending_held() -> list[dict]:
    try:
        with _conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT rowid, * FROM decisions WHERE released=0 "
                             "ORDER BY ts ASC").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def release_held(include_batched: bool = False) -> list[dict]:
    """Mark held (and optionally batched) decisions as released; returns them."""
    items = [i for i in pending_held() if include_batched or i["decision"] == HOLD]
    if items:
        with _conn() as c:
            c.executemany("UPDATE decisions SET released=1 WHERE rowid=?",
                          [(i["rowid"],) for i in items])
    return items


# ── Breakpoint detection ─────────────────────────────────────────────────────
def is_breakpoint(prev: WorkflowState | None, cur: WorkflowState,
                  recent_events: list[dict]) -> str:
    """Return a reason string if now is a natural moment to surface held items."""
    if prev is None:
        return ""
    if prev.branch and cur.branch and prev.branch != cur.branch:
        return "branch switch"
    fresh_after = datetime.now() - timedelta(seconds=TICK_SECONDS * 2)
    for e in recent_events[-5:]:
        if e.get("event_type") == "git_commit" and _parse_ts(e["timestamp"]) >= fresh_after:
            return "commit"
    if prev.deep and not cur.deep and cur.activity not in ("meeting",):
        return "left deep focus"
    if prev.activity != cur.activity and cur.activity in ("communicating",):
        return "switched to communication"
    return ""


# ── Auto context capture ─────────────────────────────────────────────────────
def summarize(state: WorkflowState, events: list[dict]) -> str:
    """Human-readable 'where was I' line, built locally from recent activity."""
    titles = [redact((e.get("details") or {}).get("title", "")) for e in events
              if e["event_type"] == "app_switch" and e.get("app") in IDE_APPS]
    files = [t.split(" - ")[0] for t in titles if t]
    last_file = files[-1] if files else ""
    parts = [f"{state.activity}"]
    if state.repo:
        parts.append(f"in {state.repo}" + (f"@{state.branch}" if state.branch else ""))
    if last_file:
        parts.append(f"on {last_file}")
    parts.append(f"({state.deep_minutes}m deep, focus {state.focus_score})")
    return " ".join(parts)


def should_auto_capture(prev: WorkflowState | None, cur: WorkflowState,
                        last_capture_ts: float, now_ts: float | None = None) -> str:
    if PRIVATE_MODE or prev is None:
        return ""
    now_ts = now_ts or time.time()
    if now_ts - last_capture_ts < AUTO_CAPTURE_COOLDOWN:
        return ""
    was_deep = prev.deep and prev.deep_minutes >= AUTO_CAPTURE_MIN_DEEP
    if not was_deep:
        return ""
    if cur.activity in ("communicating", "meeting"):
        return f"interrupted by {cur.activity}"
    if not cur.deep:
        return "focus dropped"
    return ""


def _do_auto_capture(reason: str, state: WorkflowState, events: list[dict]) -> dict:
    anchor = ""
    try:
        from deepworkai.features.context_anchor import save_anchor
        anchor = save_anchor()
    except Exception as e:
        anchor = f"anchor unavailable ({e.__class__.__name__})"
    summary = summarize(state, events)
    with _conn() as c:
        c.execute("INSERT INTO auto_context(ts, reason, activity, repo, branch, anchor, summary) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (datetime.now().isoformat(), reason, state.activity, state.repo,
                   state.branch, anchor, summary))
    log.info("[INTEL] auto-capture (%s): %s", reason, summary)
    return {"reason": reason, "summary": summary, "anchor": anchor}


def last_auto_context() -> dict:
    try:
        with _conn() as c:
            c.row_factory = sqlite3.Row
            r = c.execute("SELECT * FROM auto_context ORDER BY ts DESC LIMIT 1").fetchone()
        return dict(r) if r else {}
    except Exception:
        return {}


# ── Insights ─────────────────────────────────────────────────────────────────
def insights(days: int = 7) -> dict:
    """Local analytics: when you focus best and what interrupts you."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    out = {"best_hours": [], "deep_minutes": 0, "interruptions": {}, "held": 0, "delivered": 0}
    try:
        with _conn() as c:
            rows = c.execute("SELECT ts, focus_score, deep FROM state_log WHERE ts >= ?",
                             (since,)).fetchall()
            by_hour: dict[int, list[int]] = {}
            for ts, score, deep in rows:
                by_hour.setdefault(_parse_ts(ts).hour, []).append(score)
                out["deep_minutes"] += (TICK_SECONDS / 60) if deep else 0
            ranked = sorted(by_hour.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
            out["best_hours"] = [f"{h:02d}:00" for h, _ in ranked[:3]]
            out["deep_minutes"] = int(out["deep_minutes"])
            for src, n in c.execute("SELECT source, COUNT(*) FROM decisions WHERE ts >= ? "
                                    "GROUP BY source ORDER BY 2 DESC", (since,)):
                out["interruptions"][src or "unknown"] = n
            for dec, n in c.execute("SELECT decision, COUNT(*) FROM decisions WHERE ts >= ? "
                                    "GROUP BY decision", (since,)):
                if dec == DELIVER:
                    out["delivered"] = n
                else:
                    out["held"] += n
    except Exception as e:
        log.debug("insights failed: %s", e)
    return out


# ── Background engine ────────────────────────────────────────────────────────
_lock = threading.Lock()
_state = WorkflowState()
_prev: WorkflowState | None = None
_last_capture = 0.0
_enabled = {"auto_capture": not PRIVATE_MODE}
_thread: threading.Thread | None = None
_stop = threading.Event()
_on_release = None   # optional callback(list[dict], reason)


def current_state() -> WorkflowState:
    with _lock:
        return _state


def set_auto_capture(enabled: bool):
    _enabled["auto_capture"] = enabled and not PRIVATE_MODE


def tick(events: list[dict] | None = None) -> dict:
    """One engine step. Returns what happened (useful for tests/logging)."""
    global _state, _prev, _last_capture
    events = load_recent_events() if events is None else events
    cur = infer_state(events)
    result: dict = {"state": cur.to_dict()}
    with _lock:
        prev, _state = _state if _prev is not None else None, cur
        _prev = cur
    try:
        with _conn() as c:
            c.execute("INSERT INTO state_log VALUES (?,?,?,?)",
                      (datetime.now().isoformat(), cur.activity, cur.focus_score, int(cur.deep)))
    except Exception:
        pass

    if _enabled["auto_capture"]:
        reason = should_auto_capture(prev, cur, _last_capture)
        if reason:
            _last_capture = time.time()
            # Use the pre-interruption state for the summary: that's what you want back.
            result["auto_capture"] = _do_auto_capture(reason, prev, events)

    bp = is_breakpoint(prev, cur, events)
    if bp:
        released = release_held(include_batched=(bp == "left deep focus"))
        if released:
            result["released"] = {"reason": bp, "count": len(released)}
            log.info("[INTEL] breakpoint (%s) — releasing %d held item(s)", bp, len(released))
            if _on_release:
                try:
                    _on_release(released, bp)
                except Exception:
                    pass
    try:
        from deepworkai.service.lcd_state import set_temp_text
        if result.get("released"):
            set_temp_text(f"📬 {result['released']['count']} ready")
    except Exception:
        pass
    return result


def _loop():
    n = 0
    while not _stop.is_set():
        try:
            tick()
            n += 1
            if n % 120 == 0:            # ~hourly
                purge_old()
        except Exception as e:
            log.error("[INTEL] tick error: %s", e)
        _stop.wait(TICK_SECONDS)


def start(on_release=None):
    global _thread, _on_release
    _on_release = on_release
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    purge_old()
    _thread = threading.Thread(target=_loop, daemon=True, name="WorkflowIntel")
    _thread.start()
    log.info("[INTEL] engine started (private_mode=%s)", PRIVATE_MODE)


def stop():
    _stop.set()
