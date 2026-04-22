"""
Git Branch Pulse
================
Polls every 90 s for remote branch updates.
When a teammate pushes to your current branch, sends HAPTIC_PULSE
back through the TCP service so the plugin fires hardware haptic.
No popup. No sound. Subcortical awareness only.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

_last_hashes: dict[str, str] = {}
_lock = threading.Lock()
POLL_SEC = 90


def _run(cmd: list, cwd=None, timeout=6) -> str:
    try:
        from deepworkai.service.proc_utils import run_hidden
        r = run_hidden(cmd, cwd=cwd, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _repo_root() -> str:
    return _run(["git", "rev-parse", "--show-toplevel"])


def _current_branch(cwd: str) -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)


def _remote_hash(branch: str, cwd: str) -> str:
    """Fetch silently and return the remote hash."""
    _run(["git", "fetch", "origin", branch, "--quiet"], cwd=cwd, timeout=12)
    return _run(["git", "rev-parse", f"origin/{branch}"], cwd=cwd)


def _fire_haptic(pulses: int = 2):
    """Send haptic trigger via TCP loopback to the service."""
    try:
        import socket
        s = socket.socket()
        s.settimeout(1)
        s.connect(("127.0.0.1", 57321))
        s.sendall(f"HAPTIC_PULSE:{pulses}\n".encode())
        s.close()
    except Exception:
        pass  # Service not running — skip silently


def _poll():
    while True:
        try:
            cwd = _repo_root()
            if not cwd:
                time.sleep(POLL_SEC)
                continue

            branch = _current_branch(cwd)
            if not branch or branch == "HEAD":
                time.sleep(POLL_SEC)
                continue

            rhash = _remote_hash(branch, cwd)
            if not rhash:
                time.sleep(POLL_SEC)
                continue

            key = f"{cwd}:{branch}"
            with _lock:
                prev = _last_hashes.get(key)
                _last_hashes[key] = rhash

            if prev and prev != rhash:
                # Remote was updated — pulse twice
                _fire_haptic(2)
        except Exception:
            pass
        time.sleep(POLL_SEC)


def start_git_pulse():
    t = threading.Thread(target=_poll, daemon=True, name="GitPulse")
    t.start()
