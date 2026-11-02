"""
Blocker Radar — ambient LCD status for CI, PRs, and branch health.
Polls every 60 s. Updates lcd_state.py — no popups, no sounds.

Requires .env:
  GITHUB_TOKEN=ghp_...
  GITHUB_REPO=owner/repo
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from deepworkai.service.paths import DATA_DIR  # one data folder (installed app or repo)
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "radar_state.json"
POLL_SEC   = 60


def _cfg(key: str) -> str:
    from deepworkai.service.secrets_store import get
    return get(key)


def _gh(endpoint: str) -> dict | list | None:
    if os.environ.get("DEEPWORKAI_OFFLINE") == "1":
        return None
    token = _cfg("GITHUB_TOKEN")
    repo  = _cfg("GITHUB_REPO")
    if not token or not repo:
        return None
    # Input validation (OWASP ASVS V5): GITHUB_REPO must be exactly "owner/name";
    # anything else could steer the request to a different API path.
    import re
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}", repo) or ".." in repo:
        return None
    try:
        import urllib.request
        url = f"https://api.github.com/repos/{repo}/{endpoint}"   # fixed https scheme
        req = urllib.request.Request(
            url, headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "DeepWorkAI/2.0",
            }
        )
        with urllib.request.urlopen(req, timeout=8) as r:  # nosec B310 - https only, validated path
            return json.loads(r.read())
    except Exception:
        return None


def _ci_status(branch: str) -> str:
    from urllib.parse import quote
    data = _gh(f"commits/{quote(branch, safe='')}/check-runs")   # branch names may contain ?, #, ..
    if not isinstance(data, dict):
        return "unknown"
    runs = data.get("check_runs", [])
    if not runs:
        return "unknown"
    conclusions = [r.get("conclusion") for r in runs]
    if any(c == "failure" for c in conclusions):
        return "fail"
    if any(c is None for c in conclusions):
        return "pending"
    return "pass"


def _pr_count() -> int:
    data = _gh("pulls?state=open&per_page=50")
    if not isinstance(data, list):
        return 0
    return sum(
        1 for pr in data
        if pr.get("requested_reviewers")
    )


def _branch_behind(branch: str) -> int:
    """Return how many commits behind main/master the branch is."""
    for base in ("main", "master"):
        from urllib.parse import quote
        data = _gh(f"compare/{quote(base, safe='')}...{quote(branch, safe='')}")
        if isinstance(data, dict):
            return int(data.get("behind_by", 0))
    return 0


def _current_branch() -> str:
    from deepworkai.service.proc_utils import run_hidden
    r = run_hidden(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=3)
    return r.stdout.strip() if r.returncode == 0 else "main"


def _poll():
    while True:
        try:
            branch = _current_branch()
            ci     = _ci_status(branch)
            prs    = _pr_count()
            behind = _branch_behind(branch)

            state = {
                "branch":  branch,
                "ci":      ci,
                "prs":     prs,
                "behind":  behind,
                "blocked": ci == "fail" or behind > 10,
            }
            STATE_FILE.write_text(json.dumps(state))

            from deepworkai.service.lcd_state import update_radar_display
            update_radar_display(state)
        except Exception:
            pass
        time.sleep(POLL_SEC)


def start_radar():
    """Start the background polling thread."""
    t = threading.Thread(target=_poll, daemon=True, name="BlockerRadar")
    t.start()


def get_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"ci": "unknown", "prs": 0, "behind": 0, "blocked": False, "branch": "?"}
