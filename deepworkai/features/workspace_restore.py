"""
Workspace Restore — thin wrapper around deep_restore_core.
Provides a clean feature-level API for workspace capture and restore.
"""

from ..service import deep_restore_core as core


def capture() -> dict:
    """Capture current workspace and save snapshot. Returns summary dict."""
    snap = core.capture_workspace()
    cid  = core.save_snapshot(snap, "manual")
    return {
        "id":      cid[:8],
        "windows": len(snap.get("windows", [])),
        "tabs":    sum(len(v) for v in snap.get("browsers", {}).values()),
        "branch":  snap.get("git", {}).get("branch", "—"),
    }


def restore_latest() -> dict:
    """Restore the most recent workspace snapshot."""
    snap, ts, summary = core.load_latest_snapshot()
    if not snap:
        return {"error": "No snapshot found — run CAPTURE first"}
    core.restore_workspace(snap, ts)
    return {"restored": summary, "timestamp": ts}


def restore_before(minutes: int) -> dict:
    """Restore the most recent snapshot captured >= `minutes` ago."""
    snap, ts, summary = core.load_snapshot_before(minutes)
    if not snap:
        return {"error": f"No snapshot found before {minutes} min ago"}
    core.restore_workspace(snap, ts)
    return {"restored": summary, "timestamp": ts, "minutes": minutes}


def get_recent(limit: int = 5) -> list:
    """Return recent snapshot metadata."""
    return core.get_recent_snapshots(limit=limit)
