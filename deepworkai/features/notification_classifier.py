"""
Deep Work AI — Notification Priority Classifier
================================================
Classifies incoming notifications (Slack DMs, Jira tickets, GitHub PRs)
into LOW / MEDIUM / HIGH priority so the Focus Shield can decide what
to surface immediately vs hold until the session ends.

Architecture
------------
1. Rule-based fast path   — catches obvious patterns first (regex + keywords)
2. TF-IDF + LogisticReg  — sklearn model trained on bootstrap labels
3. Confidence threshold   — anything < 60 % confidence falls back to MEDIUM

Dependencies: sklearn (optional) — falls back to pure rules if not installed.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("notification_classifier")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH  = DATA_DIR / "notifications.db"

# ── Priority levels ───────────────────────────────────────────────────────────
LOW    = "LOW"
MEDIUM = "MEDIUM"
HIGH   = "HIGH"

PRIORITY_RANK = {LOW: 0, MEDIUM: 1, HIGH: 2}


# ── Data model ────────────────────────────────────────────────────────────────
@dataclass
class Notification:
    id:          str
    source:      str          # "slack" | "jira" | "github" | "manual"
    title:       str
    body:        str
    url:         str   = ""
    sender:      str   = ""
    channel:     str   = ""
    priority:    str   = MEDIUM
    confidence:  float = 0.0
    arrived_at:  str   = field(default_factory=lambda: datetime.now().isoformat())
    reviewed:    bool  = False
    held:        bool  = False   # True = withheld during Focus Shield

    def to_dict(self) -> dict:
        return asdict(self)


# ── Bootstrap training data ───────────────────────────────────────────────────
# (text, label) pairs that seed the sklearn model.
# The model re-trains each time new labelled items are added.
_BOOTSTRAP_DATA: list[tuple[str, str]] = [
    # HIGH — production incidents, blockers, urgent asks
    ("production is down site is not loading 500 errors", HIGH),
    ("URGENT: critical bug in prod blocking all users deploy asap", HIGH),
    ("build is broken can't deploy hotfix needed now", HIGH),
    ("security vulnerability found in main branch CVE exploit", HIGH),
    ("customer data breach detected investigate immediately", HIGH),
    ("payment gateway failing all transactions rejected", HIGH),
    ("p0 incident database unreachable service degraded", HIGH),
    ("server is on fire latency 10x all hands needed", HIGH),
    ("blocking issue sprint ends tomorrow need your review now", HIGH),
    ("PR review needed today release scheduled in 2 hours", HIGH),
    ("CEO needs this fixed before demo in 30 minutes", HIGH),
    ("client escalation SLA breach apology call at 3pm", HIGH),
    ("jira CRITICAL blocker assigned to you due today", HIGH),
    ("github PR urgent hotfix needs approval to merge", HIGH),
    ("your review is blocking our release please look now", HIGH),

    # MEDIUM — normal work items, scheduled things
    ("PR review requested when you get a chance", MEDIUM),
    ("code review ready please take a look this week", MEDIUM),
    ("jira ticket assigned to you sprint 22", MEDIUM),
    ("reminder standup tomorrow at 10am", MEDIUM),
    ("design feedback needed on the new dashboard mockup", MEDIUM),
    ("can you check this bug when you have time", MEDIUM),
    ("new feature request added to backlog", MEDIUM),
    ("jenkins build succeeded on main branch", MEDIUM),
    ("weekly sync moved to Thursday at 2pm", MEDIUM),
    ("ticket updated status changed to in progress", MEDIUM),
    ("PR merged to develop branch", MEDIUM),
    ("deployment to staging complete ready for QA", MEDIUM),
    ("jira story points updated for next sprint", MEDIUM),
    ("github actions workflow failed on feature branch", MEDIUM),
    ("new jira epic created roadmap planning", MEDIUM),

    # LOW — social, info, FYI, non-work
    ("hey how are you doing", LOW),
    ("happy birthday have a great day", LOW),
    ("lunch today at 12:30 at the usual place", LOW),
    ("FYI newsletter edition 42 is out", LOW),
    ("interesting article about rust programming language", LOW),
    ("watercooler anyone watching the game tonight", LOW),
    ("random standup bot daily standup time", LOW),
    ("spotify wrapped your 2024 stats are ready", LOW),
    ("new emoji added to the workspace", LOW),
    ("out of office auto reply will return monday", LOW),
    ("fun friday zoom trivia at 4pm optional", LOW),
    ("team lunch outing Friday sign up sheet", LOW),
    ("github star on your repo", LOW),
    ("your PR was automatically closed due to inactivity", LOW),
    ("jira issue closed as won't fix", LOW),
]


# ── Rule-based fast path ──────────────────────────────────────────────────────
_HIGH_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(urgent|asap|critical|p0|p1|blocker|blocking|hotfix|incident|breach|down|broken|fire)\b",
        r"\b(production|prod)\s+(down|broken|fail|error|unreachable)\b",
        r"\b(review|approval|merge)\s+needed\s+(today|now|asap|immediately|urgent)\b",
        r"\b(sla|breach|escalat|customer\s+data|security\s+vuln|cve)\b",
        r"release\s+(in|scheduled|today|now|tonight|at\s+\d)",
        r"\b(blocked|blocking)\s+.{0,30}(you|your|team|release|deploy)\b",
        r"@(here|channel|everyone)\b",
    ]
]

_LOW_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\b(lunch|birthday|trivia|fun\s+friday|watercooler|happy|congrats|fyi\b|newsletter|spotify)\b",
        r"\b(auto[-\s]?reply|out[-\s]of[-\s]office|ooo|vacation)\b",
        r"\b(standup\s+bot|daily\s+standup|scrum\s+bot)\b",
        r"\b(won.?t\s+fix|closed\s+as|duplicate|auto[-\s]closed|stale)\b",
        r"\b(new\s+emoji|team\s+lunch|happy\s+hour|optional|sign[-\s]up)\b",
    ]
]

_GITHUB_PR_READY_PAT = re.compile(
    r"(review\s+requested|ready\s+for\s+review|please\s+review|needs?\s+review)", re.IGNORECASE
)
_JIRA_CRITICAL_PAT = re.compile(
    r"\b(critical|blocker|urgent)\b.*\b(assigned|due\s+today|overdue|sprint\s+end)\b",
    re.IGNORECASE,
)


def _rule_classify(text: str, source: str = "") -> tuple[str | None, float]:
    """
    Fast rule-based classification. Returns (priority, confidence) or
    (None, 0.0) when no rule fires (fall through to ML model).
    """
    combined = text.strip().lower()

    # Definite HIGH rules
    for pat in _HIGH_PATTERNS:
        if pat.search(combined):
            return HIGH, 0.95

    # Source-specific HIGH signals
    if source == "jira" and _JIRA_CRITICAL_PAT.search(combined):
        return HIGH, 0.90
    if source == "github" and "urgent" in combined and _GITHUB_PR_READY_PAT.search(combined):
        return HIGH, 0.88

    # Definite LOW rules
    for pat in _LOW_PATTERNS:
        if pat.search(combined):
            return LOW, 0.90

    # PR review requested → MEDIUM by default (not urgent, but real work)
    if source == "github" and _GITHUB_PR_READY_PAT.search(combined):
        return MEDIUM, 0.80

    return None, 0.0   # no rule matched


# ── sklearn Model ─────────────────────────────────────────────────────────────
_model = None
_vectorizer = None
_model_trained = False


def _build_model():
    """Train TF-IDF + LogisticRegression on bootstrap + stored labelled items."""
    global _model, _vectorizer, _model_trained
    try:
        from sklearn.pipeline import Pipeline
        from sklearn.linear_model import LogisticRegression
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts, labels = zip(*_BOOTSTRAP_DATA)  # type: ignore[misc]

        # Add any user-labelled items from the DB
        try:
            labelled = _get_labelled_from_db()
            if labelled:
                extra_t, extra_l = zip(*labelled)
                texts  = list(texts) + list(extra_t)
                labels = list(labels) + list(extra_l)
        except Exception:
            pass

        pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=2000,
                                      sublinear_tf=True)),
            ("clf",   LogisticRegression(max_iter=300, C=1.5,
                                         class_weight="balanced")),
        ])
        pipeline.fit(texts, labels)
        _model = pipeline
        _model_trained = True
        log.info("[CLASSIFIER] sklearn model trained on %d samples", len(texts))
    except ImportError:
        log.info("[CLASSIFIER] sklearn not installed — using rule-based classifier only")
    except Exception as e:
        log.warning("[CLASSIFIER] Model training failed: %s", e)


def _sklearn_classify(text: str) -> tuple[str, float]:
    """Return (priority, confidence) from the sklearn model."""
    global _model, _model_trained
    if not _model_trained:
        _build_model()
    if _model is None:
        return MEDIUM, 0.5   # sklearn unavailable

    try:
        proba = _model.predict_proba([text])[0]
        classes = _model.classes_
        idx = proba.argmax()
        return classes[idx], float(proba[idx])
    except Exception:
        return MEDIUM, 0.5


# ── Public classifier API ─────────────────────────────────────────────────────
def classify(text: str, source: str = "", sender: str = "") -> tuple[str, float]:
    """
    Main entry point. Returns (priority, confidence).
      priority   : "LOW" | "MEDIUM" | "HIGH"
      confidence : 0.0 – 1.0
    """
    combined = f"{text}"
    if sender:
        combined = f"{sender}: {combined}"

    # 1. Rule-based fast path
    rule_priority, rule_conf = _rule_classify(combined, source)
    if rule_priority and rule_conf >= 0.85:
        return rule_priority, rule_conf

    # 2. ML model
    ml_priority, ml_conf = _sklearn_classify(combined)

    # 3. Blend: if rule fired with lower confidence, weight it
    if rule_priority and ml_conf < 0.70:
        return rule_priority, max(rule_conf, ml_conf)

    # 4. Low-confidence ML result → MEDIUM
    if ml_conf < 0.60:
        return MEDIUM, ml_conf

    return ml_priority, ml_conf


def classify_notification(n: Notification) -> Notification:
    """Classify a Notification in-place and return it."""
    text = f"{n.title} {n.body}"
    n.priority, n.confidence = classify(text, source=n.source, sender=n.sender)
    return n


# ── Database ──────────────────────────────────────────────────────────────────
def _init_db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS notifications (
            id          TEXT PRIMARY KEY,
            source      TEXT DEFAULT '',
            title       TEXT DEFAULT '',
            body        TEXT DEFAULT '',
            url         TEXT DEFAULT '',
            sender      TEXT DEFAULT '',
            channel     TEXT DEFAULT '',
            priority    TEXT DEFAULT 'MEDIUM',
            confidence  REAL DEFAULT 0.5,
            arrived_at  TEXT NOT NULL,
            reviewed    INTEGER DEFAULT 0,
            held        INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_arrived ON notifications(arrived_at DESC);
        CREATE INDEX IF NOT EXISTS idx_priority ON notifications(priority);

        CREATE TABLE IF NOT EXISTS labelled (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            text    TEXT NOT NULL,
            label   TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


def _get_labelled_from_db() -> list[tuple[str, str]]:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=3)
        rows = conn.execute("SELECT text, label FROM labelled").fetchall()
        conn.close()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []


def save_notification(n: Notification):
    """Persist a classified notification to the DB."""
    try:
        _init_db()
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("""
            INSERT OR REPLACE INTO notifications
            (id, source, title, body, url, sender, channel,
             priority, confidence, arrived_at, reviewed, held)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (n.id, n.source, n.title, n.body, n.url, n.sender, n.channel,
              n.priority, n.confidence, n.arrived_at,
              int(n.reviewed), int(n.held)))
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("[CLASSIFIER] save_notification error: %s", e)


def get_held_notifications(priority_filter: str = "") -> list[dict]:
    """Return held (withheld during shield) notifications, newest first."""
    try:
        _init_db()
        conn = sqlite3.connect(DB_PATH, timeout=3)
        if priority_filter:
            rows = conn.execute(
                "SELECT id,source,title,body,url,sender,channel,priority,confidence,arrived_at "
                "FROM notifications WHERE held=1 AND reviewed=0 AND priority=? "
                "ORDER BY arrived_at DESC", (priority_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,source,title,body,url,sender,channel,priority,confidence,arrived_at "
                "FROM notifications WHERE held=1 AND reviewed=0 "
                "ORDER BY priority DESC, arrived_at DESC"
            ).fetchall()
        conn.close()
        cols = ["id","source","title","body","url","sender","channel",
                "priority","confidence","arrived_at"]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        log.error("[CLASSIFIER] get_held_notifications error: %s", e)
        return []


def get_all_unreviewed(limit: int = 50) -> list[dict]:
    """Return all unreviewed notifications sorted HIGH→LOW."""
    try:
        _init_db()
        conn = sqlite3.connect(DB_PATH, timeout=3)
        rows = conn.execute("""
            SELECT id,source,title,body,url,sender,channel,priority,confidence,arrived_at,held
            FROM notifications WHERE reviewed=0
            ORDER BY
              CASE priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END,
              arrived_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        cols = ["id","source","title","body","url","sender","channel",
                "priority","confidence","arrived_at","held"]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        log.error("[CLASSIFIER] get_all_unreviewed error: %s", e)
        return []


def mark_reviewed(notification_id: str):
    """Mark a notification as reviewed (dismissed from triage)."""
    try:
        _init_db()
        conn = sqlite3.connect(DB_PATH, timeout=3)
        conn.execute("UPDATE notifications SET reviewed=1 WHERE id=?",
                     (notification_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("[CLASSIFIER] mark_reviewed error: %s", e)


def label_and_retrain(notification_id: str, correct_label: str):
    """
    User corrects a classification → save as training example → retrain model.
    This is the feedback loop that improves the model over time.
    """
    try:
        _init_db()
        conn = sqlite3.connect(DB_PATH, timeout=3)
        row = conn.execute(
            "SELECT title, body FROM notifications WHERE id=?",
            (notification_id,)
        ).fetchone()
        if row:
            text = f"{row[0]} {row[1]}".strip()
            conn.execute("INSERT INTO labelled (text, label) VALUES (?,?)",
                         (text, correct_label))
            conn.commit()
        conn.close()
        # Retrain immediately
        _build_model()
        log.info("[CLASSIFIER] Retrained with new label: %s → %s",
                 notification_id[:8], correct_label)
    except Exception as e:
        log.error("[CLASSIFIER] label_and_retrain error: %s", e)


def inject_notification(source: str, title: str, body: str, url: str = "",
                        sender: str = "", channel: str = "",
                        held: bool = True) -> Notification:
    """
    Create, classify, and save a notification.
    `held=True` means it was captured during Focus Shield and withheld.
    Returns the classified Notification object.
    """
    import uuid
    _init_db()
    n = Notification(
        id=str(uuid.uuid4()),
        source=source,
        title=title,
        body=body,
        url=url,
        sender=sender,
        channel=channel,
        held=held,
    )
    classify_notification(n)
    # Context-aware interruption management: hold/batch unless it is worth
    # breaking the user's current focus for.
    try:
        from deepworkai.features.workflow_intelligence import route_notification, DELIVER
        decision = route_notification(n.to_dict(), shield_active=held)
        n.held = held or decision != DELIVER
        log.info("[CLASSIFIER] routing → %s", decision)
    except Exception as e:
        log.debug("[CLASSIFIER] routing unavailable: %s", e)
    save_notification(n)
    log.info("[CLASSIFIER] %s [%s %.0f%%] from %s: %s",
             n.source, n.priority, n.confidence * 100, n.sender or "?", n.title[:60])
    return n


def count_by_priority() -> dict:
    """Return {LOW: N, MEDIUM: N, HIGH: N} for unreviewed notifications."""
    try:
        _init_db()
        conn = sqlite3.connect(DB_PATH, timeout=3)
        rows = conn.execute(
            "SELECT priority, COUNT(*) FROM notifications "
            "WHERE reviewed=0 GROUP BY priority"
        ).fetchall()
        conn.close()
        out = {LOW: 0, MEDIUM: 0, HIGH: 0}
        for priority, count in rows:
            if priority in out:
                out[priority] = count
        return out
    except Exception:
        return {LOW: 0, MEDIUM: 0, HIGH: 0}


# Pre-train model on import (non-blocking — fails silently)
try:
    _build_model()
except Exception:
    pass
