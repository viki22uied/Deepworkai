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


def _get_vscode_active_file() -> dict:
    """
    Probe VS Code / Cursor for active file + line via their CLI.
    Falls back to reading workspaceStorage JSON.
    Returns {"file": str, "line": int}
    """
    # Method 1: VS Code --status flag outputs active file info on some versions
    for cli in ["cursor", "code"]:
        out = _run([cli, "--status"], timeout=4)
        if out:
            for line in out.splitlines():
                if ":" in line and ("\\") in line or "/" in line:
                    parts = line.strip().split(":")
                    if len(parts) >= 2:
                        try:
                            return {"file": parts[0].strip(), "line": int(parts[1])}
                        except ValueError:
                            pass

    # Method 2: Read recently modified VS Code backup files
    storage_roots = [
        Path.home() / "AppData" / "Roaming" / "Code"    / "User" / "workspaceStorage",
        Path.home() / "AppData" / "Roaming" / "Cursor"  / "User" / "workspaceStorage",
    ]
    for root in storage_roots:
        if not root.exists():
            continue
        try:
            backups = sorted(root.rglob("*.json"),
                             key=lambda f: f.stat().st_mtime, reverse=True)
            for bf in backups[:5]:
                data = json.loads(bf.read_text(encoding="utf-8", errors="ignore"))
                entries = data.get("entries", [])
                if entries:
                    resource = entries[0].get("resource", "")
                    if resource.startswith("file:///"):
                        resource = resource[8:].replace("/", "\\")
                    line = entries[0].get("selection", {}).get("startLineNumber", 1)
                    return {"file": resource, "line": int(line)}
        except Exception:
            continue

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

    # Try cursor first, then code
    for cli in ["cursor", "code"]:
        result = _run([cli, "--goto", f"{fpath}:{line}"], timeout=5)
        file_label = Path(fpath).name
        msg = f"→ {file_label}:{line}"
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
