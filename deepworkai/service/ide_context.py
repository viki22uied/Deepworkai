"""
IDE context — which project and file you're actually in (VS Code / Cursor).

Replaces three broken lookups:
  * the recorder ran `git` in the *service's* directory, so it always reported
    the Deep Work AI repo instead of your project;
  * snapshot capture read `windowState` (real key: `windowsState`) from an old
    storage location and never URL-decoded `file:///d%3A/...` paths;
  * Cognitive Rewind only split window titles on an em dash, but VS Code's
    default title separator is " - ".
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

_APPS = ("Code", "Code - Insiders", "Cursor", "VSCodium")
_TITLE_SUFFIX = re.compile(r"\s+[-—–]\s+(Visual Studio Code(?: - Insiders)?|Cursor|VSCodium)\s*$")
_SEP = re.compile(r"\s+[-—–]\s+")
_cache: dict = {"t": 0.0, "folders": []}


def parse_title(title: str) -> tuple[str, str]:
    """'● app.py - my-repo - Visual Studio Code' → ('app.py', 'my-repo')."""
    if not title:
        return "", ""
    t = _TITLE_SUFFIX.sub("", title.strip()).lstrip("●• ").strip()
    parts = [p.strip() for p in _SEP.split(t) if p.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return ("", parts[0]) if "." not in parts[0] else (parts[0], "")
    return parts[0], parts[1].replace(" (Workspace)", "")


def uri_to_path(uri: str) -> str:
    """'file:///d%3A/work/api' → 'd:/work/api' (Windows) or '/home/x/api'."""
    if not uri:
        return ""
    if not uri.startswith("file:"):
        return uri
    p = unquote(urlparse(uri).path)
    if re.match(r"^/[A-Za-z]:", p):          # /d:/work → d:/work
        p = p[1:]
    return p


def _storage_files() -> list[Path]:
    base = Path(os.environ.get("APPDATA", "")) if os.name == "nt" else Path.home() / ".config"
    out = []
    for app in _APPS:
        out += [base / app / "User" / "globalStorage" / "storage.json", base / app / "storage.json"]
    return [f for f in out if f.exists()]


def _folders_from_storage(data: dict) -> list[str]:
    ws = data.get("windowsState") or data.get("windowState") or {}
    wins = [ws.get("lastActiveWindow") or {}] + list(ws.get("openedWindows") or [])
    out = []
    for w in wins:
        uri = w.get("folder") or (w.get("workspaceIdentifier") or {}).get("configURIPath") \
            or (w.get("workspaceIdentifier") or {}).get("configPath") or ""
        p = uri_to_path(uri)
        if p.endswith(".code-workspace"):
            p = str(Path(p).parent)
        if p and p not in out:
            out.append(p)
    return out


def known_folders(max_age: float = 30.0) -> list[str]:
    """Project folders VS Code/Cursor have open (last active first). Cached."""
    if time.time() - _cache["t"] < max_age:
        return _cache["folders"]
    folders: list[str] = []
    files = sorted(_storage_files(), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        try:
            for p in _folders_from_storage(json.loads(f.read_text(encoding="utf-8", errors="ignore"))):
                if p not in folders:
                    folders.append(p)
        except (OSError, ValueError):
            continue
    _cache.update(t=time.time(), folders=folders)
    return folders


def active_workspace(window_title: str = "") -> str:
    """Best guess at the project folder you're working in right now."""
    folders = [f for f in known_folders() if Path(f).exists()]
    _, name = parse_title(window_title)
    if name:
        for f in folders:
            if Path(f).name.lower() == name.lower():
                return f
    return folders[0] if folders else ""


# Characters that cmd.exe interprets — never pass these to a .cmd shim like `code`.
_CMD_META = re.compile(r'[&|<>^%"\r\n]')


def safe_cli_arg(arg: str) -> bool:
    return bool(arg) and not _CMD_META.search(arg)
