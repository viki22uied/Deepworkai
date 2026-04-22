"""
Deep Work AI — Notification Interceptor
=========================================
Background poller that fetches notifications from GitHub, Jira, and Slack
during a Focus Shield session and stores them in the classifier DB.

• Runs as a daemon thread inside deepwork_service.py
• Polls every 60 s while shield is active, pauses when shield is off
• HIGH-priority items are logged so the service can optionally alert
• Falls back gracefully when tokens are not configured
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("notification_interceptor")

# ── Config helpers ─────────────────────────────────────────────────────────────
_BASE_DIR = Path(__file__).parent.parent.parent

def _load_env() -> dict:
    """Load .env file into a dict (supplements os.environ)."""
    env: dict = {}
    env_file = _BASE_DIR / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass
    return env


_ENV = _load_env()


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, _ENV.get(key, default))


# ── State ─────────────────────────────────────────────────────────────────────
_shield_active   = False
_poller_thread: Optional[threading.Thread] = None
_stop_event      = threading.Event()
_last_poll: dict = {}          # {source: last_fetched_timestamp}
_new_high_count  = 0           # high-priority items since shield went on


def set_shield_state(active: bool):
    """Called by deepwork_service when shield is toggled."""
    global _shield_active, _new_high_count
    _shield_active = active
    if active:
        _new_high_count = 0
        _start_poller()
        log.info("[INTERCEPTOR] Shield ON — notification polling started")
    else:
        log.info("[INTERCEPTOR] Shield OFF — polling paused")


def get_high_count() -> int:
    """How many HIGH-priority items arrived since shield was activated."""
    return _new_high_count


# ── Poller thread ─────────────────────────────────────────────────────────────
_POLL_INTERVAL = 60   # seconds between polls


def _start_poller():
    global _poller_thread
    if _poller_thread and _poller_thread.is_alive():
        return
    _stop_event.clear()
    _poller_thread = threading.Thread(
        target=_poll_loop, daemon=True, name="NotifPoller"
    )
    _poller_thread.start()


def _poll_loop():
    while not _stop_event.is_set():
        if _shield_active:
            try:
                _poll_all()
            except Exception as e:
                log.error("[INTERCEPTOR] Poll error: %s", e)
        _stop_event.wait(timeout=_POLL_INTERVAL)


def _poll_all():
    """Run all source pollers; each is independent and silently fails."""
    _poll_github()
    _poll_jira()
    _poll_slack()


# ── GitHub ─────────────────────────────────────────────────────────────────────
def _poll_github():
    token = _cfg("GITHUB_TOKEN")
    if not token:
        return
    try:
        import requests
        since = _last_poll.get("github",
                               (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        resp = requests.get(
            "https://api.github.com/notifications",
            headers={"Authorization": f"token {token}",
                     "Accept": "application/vnd.github+json"},
            params={"all": "false", "since": since},
            timeout=8,
        )
        if resp.status_code != 200:
            return
        _last_poll["github"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        _ingest_github(resp.json())
    except Exception as e:
        log.debug("[INTERCEPTOR] GitHub error: %s", e)


def _ingest_github(items: list):
    global _new_high_count
    from deepworkai.features.notification_classifier import inject_notification, HIGH
    for item in items[:20]:
        subject  = item.get("subject", {})
        repo     = item.get("repository", {}).get("full_name", "")
        kind     = subject.get("type", "")        # "PullRequest", "Issue", etc.
        title    = subject.get("title", "")
        url      = subject.get("url", "") or subject.get("html_url", "")
        reason   = item.get("reason", "")         # subscribed, mention, review_requested …
        notif_id = f"gh-{item.get('id', '')}"

        body = f"{kind} in {repo}. Reason: {reason}."
        sender = repo.split("/")[0] if "/" in repo else repo

        n = inject_notification(
            source="github", title=title, body=body,
            url=url, sender=sender, channel=repo, held=True
        )
        if n.priority == HIGH:
            _new_high_count += 1
            log.info("[INTERCEPTOR] HIGH GitHub: %s", title[:80])


# ── Jira ──────────────────────────────────────────────────────────────────────
def _poll_jira():
    jira_url   = _cfg("JIRA_URL")
    jira_email = _cfg("JIRA_EMAIL")
    jira_token = _cfg("JIRA_TOKEN")
    if not (jira_url and jira_email and jira_token):
        return
    try:
        import requests, base64
        creds = base64.b64encode(f"{jira_email}:{jira_token}".encode()).decode()
        # Issues assigned to me, updated recently
        jql = (
            "assignee = currentUser() AND "
            "updated >= -2h AND "
            "status NOT IN (Done, Closed, Resolved) "
            "ORDER BY updated DESC"
        )
        resp = requests.get(
            f"{jira_url.rstrip('/')}/rest/api/3/search",
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/json"},
            params={"jql": jql, "maxResults": 15,
                    "fields": "summary,description,priority,status,assignee"},
            timeout=8,
        )
        if resp.status_code != 200:
            return
        _last_poll["jira"] = datetime.utcnow().isoformat()
        _ingest_jira(resp.json().get("issues", []))
    except Exception as e:
        log.debug("[INTERCEPTOR] Jira error: %s", e)


def _ingest_jira(issues: list):
    global _new_high_count
    from deepworkai.features.notification_classifier import inject_notification, HIGH
    for issue in issues:
        key     = issue.get("key", "")
        fields  = issue.get("fields", {})
        summary = fields.get("summary", "")
        jira_p  = (fields.get("priority") or {}).get("name", "")
        status  = (fields.get("status")   or {}).get("name", "")
        desc_raw = fields.get("description") or {}
        # Jira description is Atlassian Document Format (ADF) — extract plain text
        desc = _adf_to_text(desc_raw) if isinstance(desc_raw, dict) else str(desc_raw)
        notif_id = f"jira-{key}"

        title = f"{key} — {summary}"
        body  = f"Status: {status}. Priority: {jira_p}. {desc[:300]}"

        n = inject_notification(
            source="jira", title=title, body=body,
            sender="jira", channel="", held=True
        )
        if n.priority == HIGH:
            _new_high_count += 1
            log.info("[INTERCEPTOR] HIGH Jira: %s", title[:80])


def _adf_to_text(adf: dict, depth: int = 0) -> str:
    """Recursively extract text from Atlassian Document Format."""
    if depth > 8:
        return ""
    parts = []
    if isinstance(adf, dict):
        if adf.get("type") == "text":
            parts.append(adf.get("text", ""))
        for child in adf.get("content", []):
            parts.append(_adf_to_text(child, depth + 1))
    return " ".join(p for p in parts if p)[:500]


# ── Slack ─────────────────────────────────────────────────────────────────────
def _poll_slack():
    token = _cfg("SLACK_TOKEN")
    if not token:
        return
    try:
        import requests
        # Poll DMs and mentions since last check
        oldest = _last_poll.get("slack",
                                str(time.time() - 7200))  # default: last 2 hours
        headers = {"Authorization": f"Bearer {token}"}

        # 1. DM channels with unread messages
        convs = requests.get(
            "https://slack.com/api/conversations.list",
            headers=headers,
            params={"types": "im", "limit": 10, "exclude_archived": "true"},
            timeout=8,
        ).json()

        messages = []
        for ch in convs.get("channels", [])[:5]:
            if not ch.get("is_open") and not ch.get("unread_count", 0):
                continue
            hist = requests.get(
                "https://slack.com/api/conversations.history",
                headers=headers,
                params={"channel": ch["id"], "oldest": oldest, "limit": 10},
                timeout=8,
            ).json()
            for m in hist.get("messages", []):
                if m.get("subtype"):    # skip join/leave/bot messages
                    continue
                messages.append({
                    "channel": ch.get("name", ch["id"]),
                    "text":    m.get("text", ""),
                    "user":    m.get("user", ""),
                    "ts":      m.get("ts", ""),
                })

        _last_poll["slack"] = str(time.time())
        _ingest_slack(messages)
    except Exception as e:
        log.debug("[INTERCEPTOR] Slack error: %s", e)


def _ingest_slack(messages: list):
    global _new_high_count
    from deepworkai.features.notification_classifier import inject_notification, HIGH
    for m in messages[:20]:
        text    = m.get("text", "").strip()
        sender  = m.get("user", "")
        channel = m.get("channel", "")
        ts      = m.get("ts", "")
        if not text:
            continue
        notif_id = f"slack-{ts}"

        # Truncate long messages
        title = text[:120]
        body  = text[:500] if len(text) > 120 else ""

        n = inject_notification(
            source="slack", title=title, body=body,
            sender=sender, channel=channel, held=True
        )
        if n.priority == HIGH:
            _new_high_count += 1
            log.info("[INTERCEPTOR] HIGH Slack: %s", title[:80])


# ── Manual inject (for testing / service command) ─────────────────────────────
def add_manual(source: str, title: str, body: str = "",
               sender: str = "", channel: str = "", url: str = "") -> dict:
    """Inject a notification manually (used by QUEUE_NOTE command)."""
    from deepworkai.features.notification_classifier import inject_notification
    n = inject_notification(
        source=source, title=title, body=body,
        sender=sender, channel=channel, url=url,
        held=_shield_active,
    )
    return n.to_dict()
