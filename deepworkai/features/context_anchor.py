"""
Context Anchor
==============
Hold button (800ms) → saves cursor-level context (file + line + note).
Tap button          → restores to exact file:line in VS Code / Cursor IDE.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR    = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

DATA_DIR    = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
ANCHOR_FILE = DATA_DIR / "context_anchor.json"


def _run(cmd: list, cwd=None, timeout=3) -> str:
    """Run a command silently, return stdout or ''."""
    try:
        from deepworkai.service.proc_utils import run_hidden
        r = run_hidden(cmd, cwd=cwd, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _last_ide_title() -> str:
    """Most recent VS Code/Cursor window title seen by the activity recorder."""
    import sqlite3
    db = DATA_DIR / "activity.db"
    if not db.exists():
        return ""
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        row = conn.execute(
            "SELECT details FROM events WHERE event_type='app_switch' "
            "AND app IN ('VS Code','Cursor') ORDER BY timestamp DESC LIMIT 1").fetchone()
        conn.close()
        return (json.loads(row[0]) or {}).get("title", "") if row and row[0] else ""
    except Exception:
        return ""


def _find_in_workspace(workspace: str, name: str) -> str:
    """Locate `name` inside the project: changed files first, then a bounded walk."""
    import os
    root = Path(workspace)
    changed = _run(["git", "diff", "--name-only"], cwd=workspace, timeout=3).splitlines()
    for rel in changed:
        if Path(rel).name == name and (root / rel).exists():
            return str(root / rel)
    skip = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".next", "target"}
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        if name in filenames:
            return str(Path(dirpath) / name)
        seen += len(filenames)
        if seen > 20000:            # keep it fast on huge monorepos
            break
    return ""


def _get_vscode_active_file() -> dict:
    """
    The file you're in, from the IDE window title + the open project folder.
    Returns {"file": str, "line": int}. VS Code doesn't expose the cursor line
    to other processes, so the line defaults to 1 unless the title carries it.
    """
    from deepworkai.service.ide_context import active_workspace, parse_title
    title = _last_ide_title()
    name, _ = parse_title(title)
    workspace = active_workspace(title)
    if name and workspace:
        found = _find_in_workspace(workspace, name)
        if found:
            return {"file": found, "line": 1}
    return {"file": "", "line": 1}


def _get_last_terminal_cmd() -> str:
    """Read last line from PowerShell history."""
    hist = (Path.home() / "AppData" / "Roaming" / "Microsoft" /
            "Windows" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt")
    if hist.exists():
        try:
            lines = hist.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            return lines[-1].strip() if lines else ""
        except Exception:
            pass
    return ""


def save_anchor() -> str:
    """Save cursor-level context. Returns human-readable confirmation."""
    from deepworkai.features.micro_journal import get_note
    ctx      = _get_vscode_active_file()
    note     = get_note() or ""
    last_cmd = _get_last_terminal_cmd()

    anchor = {
        "timestamp":    datetime.now().isoformat(),
        "file":         ctx["file"],
        "line":         ctx["line"],
        "last_command": last_cmd,
        "note":         note,
    }
    ANCHOR_FILE.write_text(json.dumps(anchor, indent=2))

    file_label = Path(ctx["file"]).name if ctx["file"] else "?"
    return f"anchored {file_label}:{ctx['line']}"


def restore_anchor() -> str:
    """Open IDE at the exact anchored file:line."""
    if not ANCHOR_FILE.exists():
        return "no anchor saved — hold button first to anchor"

    try:
        anchor = json.loads(ANCHOR_FILE.read_text())
    except Exception:
        return "anchor file corrupt"

    fpath = anchor.get("file", "")
    line  = anchor.get("line", 1)
    note  = anchor.get("note", "")

    if not fpath:
        return "anchor has no file path"

    from deepworkai.service.ide_context import safe_cli_arg
    if not safe_cli_arg(str(fpath)):
        # `code`/`cursor` are .cmd shims run by cmd.exe — & | < > ^ % " would execute.
        return f"path has unsafe characters — open {Path(fpath).name}:{line} manually"

    # Use whichever editor CLI is actually installed (Cursor first, then VS Code)
    import shutil
    for cli in ["cursor", "code"]:
        exe = shutil.which(cli)
        if not exe:
            continue
        from deepworkai.service.proc_utils import popen_hidden
        popen_hidden([exe, "--goto", f"{fpath}:{line}"])
        msg = f"→ {Path(fpath).name}:{line}"
        if note:
            msg += f" | {note[:40]}"
        return msg

    return f"no IDE CLI found — open {Path(fpath).name}:{line} manually"


def get_anchor() -> dict:
    """Return the saved anchor dict or {}."""
    if not ANCHOR_FILE.exists():
        return {}
    try:
        return json.loads(ANCHOR_FILE.read_text())
    except Exception:
        return {}
