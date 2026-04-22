"""
Deep Work AI — Slack Integration
=================================
Focus Shield: notification filtering and DND management.
Triage Dashboard: grouped notification review.

What this module does:
  • Focus Shield ON  → sets Slack DND, captures current channel context
  • Focus Shield OFF → clears DND, shows queued Slack notifications summary
  • Context capture  → saves which Slack workspace + channel was active
  • Context restore  → opens Slack to the saved channel via URL scheme

Requires SLACK_TOKEN in .env (optional — degrades gracefully without it).
DND and notification control use the Slack Web API (no additional dependencies
beyond `requests`, which is already used in the project).
"""

import json
import logging
import os
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger("slack_integration")

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.parent
# Fix: Data dir is usually at root but service script parent parent is also root
# Let's ensure BASE_DIR is actually the project root d:\Deepworkai-main
if BASE_DIR.name == "service":
    BASE_DIR = BASE_DIR.parent.parent

DATA_DIR    = BASE_DIR / "data"
DB_PATH     = DATA_DIR / "capsules.db"

SLACK_API   = "https://slack.com/api"
SLACK_TOKEN: str = ""          # loaded from env in init()
_dnd_active: bool = False      # module-level shield state


def _load_token() -> str:
    """Load SLACK_TOKEN from .env file or environment variable."""
    # 1. Check live environment
    token = os.environ.get("SLACK_TOKEN", "")
    if token:
        return token

    # 2. Parse .env file
    # Look in project root
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("SLACK_TOKEN=") and not line.startswith("#"):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return token
        except Exception:
            pass
    return ""


def init():
    """Load config. Call once at service start."""
    global SLACK_TOKEN
    SLACK_TOKEN = _load_token()
    if SLACK_TOKEN:
        log.info("[SLACK] Token loaded — full integration enabled")
    else:
        log.info("[SLACK] No token — Slack integration in offline mode "
                 "(set SLACK_TOKEN in .env to enable)")


def _api(method: str, endpoint: str, **kwargs) -> dict:
    """
    Make a Slack Web API call. Returns parsed JSON or {} on error.
    Always non-blocking — fails silently so the service keeps running.
    """
    if not SLACK_TOKEN:
        return {}
    try:
        import requests
        headers = {"Authorization": f"Bearer {SLACK_TOKEN}"}
        url     = f"{SLACK_API}/{endpoint}"
        r       = requests.request(method, url, headers=headers,
                                   timeout=5, **kwargs)
        data    = r.json()
        if not data.get("ok"):
            log.warning("[SLACK] API %s %s: %s",
                        method, endpoint, data.get("error", "unknown"))
        return data
    except Exception as e:
        log.debug("[SLACK] API call failed (%s): %s", endpoint, e)
        return {}


# ── DND (Focus Shield) ────────────────────────────────────────────────────────
def enable_dnd(minutes: int = 90) -> bool:
    """
    Pause Slack DND for `minutes` minutes.
    This is the Focus Shield — blocks notifications while the user is in
    deep work mode.
    Returns True if DND was set successfully.
    """
    global _dnd_active
    data = _api("POST", "dnd.setSnooze", json={"num_minutes": minutes})
    if data.get("ok"):
        _dnd_active = True
        log.info("[SLACK] DND enabled for %d minutes", minutes)
        return True

    log.info("[SLACK] Cannot automatically set DND (no API token configured in .env)")
    return False


def disable_dnd() -> bool:
    """
    End Slack DND. Call when the user ends a focus session.
    Restores full communication channel after deep work.
    """
    global _dnd_active
    data = _api("POST", "dnd.endSnooze")
    if data.get("ok"):
        _dnd_active = False
        log.info("[SLACK] DND disabled")
        return True

    log.info("[SLACK] DND disable attempted (no API — manual action needed)")
    _dnd_active = False
    return False


def get_dnd_status() -> dict:
    """Return current DND status for the authenticated user."""
    return _api("GET", "dnd.info")


# ── Active Channel Detection ──────────────────────────────────────────────────
def get_active_channel_context() -> dict:
    """
    Read the currently active Slack workspace and channel.

    Strategy 1: Slack desktop app stores its state in LevelDB.
    We fall back to a JSON state file if LevelDB is unavailable.
    Returns {"workspace_id": str, "channel_id": str, "channel_name": str}.
    """
    ctx: dict = {
        "workspace_id": "",
        "channel_id":   "",
        "channel_name": "",
        "workspace_url": "",
    }

    # Strategy 1: Slack's localStorage equivalent (JSON state in AppData)
    slack_appdata = Path(os.environ.get("APPDATA", "")) / "Slack"
    storage_dir   = slack_appdata / "storage"
    if storage_dir.exists():
        state_file = storage_dir / "slack-workspaces"
        if state_file.exists():
            try:
                raw = state_file.read_text(encoding="utf-8", errors="ignore")
                # Slack stores as JSON
                data = json.loads(raw)
                # Find active workspace
                for ws_id, ws_data in data.items():
                    if isinstance(ws_data, dict):
                        ctx["workspace_id"] = ws_id
                        ctx["workspace_url"] = ws_data.get("url", "")
                        break
            except Exception:
                pass

    # Strategy 2: Use Slack API to get current user's info
    if SLACK_TOKEN:
        auth = _api("GET", "auth.test")
        if auth.get("ok"):
            ctx["workspace_id"] = auth.get("team_id", "")
            ctx["workspace_url"] = auth.get("url", "")

    return ctx


# ── Notification Triage ───────────────────────────────────────────────────────
def get_queued_notifications(limit: int = 10) -> list[dict]:
    """
    Fetch recent Slack DMs and mentions that arrived while DND was active.
    Returns list of {"from": str, "text": str, "channel": str, "ts": str}.
    Used by the Triage Dashboard.
    """
    if not SLACK_TOKEN:
        return []

    messages: list[dict] = []

    # Get IM (direct message) channels
    convs = _api("GET", "conversations.list",
                 params={"types": "im,mpim", "limit": 20})
    channels = convs.get("channels", [])[:5]   # limit channels checked

    for ch in channels:
        ch_id = ch.get("id", "")
        hist  = _api("GET", "conversations.history",
                     params={"channel": ch_id, "limit": 5})
        for msg in hist.get("messages", []):
            if not msg.get("text"):
                continue
            messages.append({
                "channel": ch.get("name", ch_id),
                "from":    msg.get("user", "unknown"),
                "text":    msg["text"][:200],
                "ts":      msg.get("ts", ""),
            })
            if len(messages) >= limit:
                return messages

    return messages


def post_focus_status(project_name: str = "") -> bool:
    """
    Set a Slack status to indicate the user is in deep focus mode.
    Signals to teammates that the developer is in focus.
    """
    status_text  = f"In deep focus {('— ' + project_name) if project_name else ''}"
    status_emoji = ":brain:"
    expiration   = int(time.time()) + 5400    # 90 minutes from now

    data = _api("POST", "users.profile.set", json={
        "profile": {
            "status_text":       status_text,
            "status_emoji":      status_emoji,
            "status_expiration": expiration,
        }
    })
    if data.get("ok"):
        log.info("[SLACK] Status set: %s", status_text)
        return True
    return False


def clear_focus_status() -> bool:
    """Clear the deep focus Slack status when the session ends."""
    data = _api("POST", "users.profile.set", json={
        "profile": {
            "status_text":       "",
            "status_emoji":      "",
            "status_expiration": 0,
        }
    })
    return data.get("ok", False)


# ── Slack URL Scheme ──────────────────────────────────────────────────────────
def open_channel(workspace_id: str = "", channel_id: str = "") -> bool:
    """
    Open Slack to a specific channel using the slack:// URL scheme.
    Works whether or not the API token is set.
    Restores cognitive context by returning to the right channel.
    """
    if workspace_id and channel_id:
        url = f"slack://channel?team={workspace_id}&id={channel_id}"
    elif workspace_id:
        url = f"slack://open?team={workspace_id}"
    else:
        url = "slack://"

    return _open_slack_url(url)


def _open_slack_url(url: str) -> bool:
    """Open a slack:// URL via Windows ShellExecute."""
    try:
        subprocess.Popen(
            ["explorer.exe", url],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True
    except Exception as e:
        log.warning("[SLACK] Cannot open URL %s: %s", url, e)
        return False


# ── Focus Shield Toggle ───────────────────────────────────────────────────────
def shield_on(project_name: str = "", duration_minutes: int = 90) -> dict:
    """
    Activate Focus Shield.
    → Enables DND in Slack
    → Sets deep focus status
    → Returns context dict for saving in snapshot
    """
    init()
    dnd_ok     = enable_dnd(duration_minutes)
    status_ok  = post_focus_status(project_name)
    channel    = get_active_channel_context()

    log.info("[SLACK] Shield ON — DND=%s, Status=%s", dnd_ok, status_ok)
    return {
        "shield_active":  True,
        "dnd_enabled":    dnd_ok,
        "status_set":     status_ok,
        "active_channel": channel,
        "activated_at":   datetime.now().isoformat(),
        "duration_min":   duration_minutes,
    }


def shield_off() -> dict:
    """
    Deactivate Focus Shield.
    → Ends DND
    → Clears status
    → Returns queued notifications summary
    """
    init()
    dnd_ok    = disable_dnd()
    status_ok = clear_focus_status()
    queue     = get_queued_notifications(limit=10)

    log.info("[SLACK] Shield OFF — %d queued notifications", len(queue))
    return {
        "shield_active":        False,
        "dnd_disabled":         dnd_ok,
        "status_cleared":       status_ok,
        "queued_notifications": queue,
        "deactivated_at":       datetime.now().isoformat(),
    }


def restore_slack_context(context: dict) -> bool:
    """
    Re-open Slack to the channel that was active when the snapshot was taken.
    Called during workspace restore to recover full cognitive context.
    """
    init()
    channel_ctx = context.get("active_channel", {})
    ws_id       = channel_ctx.get("workspace_id", "")
    ch_id       = channel_ctx.get("channel_id", "")

    if ws_id or ch_id:
        return open_channel(ws_id, ch_id)
    return False
