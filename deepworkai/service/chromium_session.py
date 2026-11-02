"""
Chromium / Brave / Edge session-file reader — returns the tabs that are
*actually open right now*, in window/tab order.

Why this exists
---------------
Chromium keeps two kinds of SNSS files in <profile>/Sessions/:
  * Session_<time>  — the live session (open windows/tabs)       ← what we want
  * Tabs_<time>     — the "recently closed" list (Ctrl+Shift+T)  ← NOT open tabs
Both are append-only *command logs*: every navigation in every tab, every
tab/window close, is appended. Scraping every URL out of the bytes (the old
approach, on Tabs_*) returns closed tabs and old back/forward history — which
is why restore used to reopen tabs from days or months ago.

This module replays the command log and keeps only, for each tab that was
never closed, the URL at its currently selected navigation index.

File format: "SNSS" magic, int32 version, then records of
  uint16 size | uint8 command_id | (size-1) bytes payload
"""

from __future__ import annotations

import struct
from pathlib import Path

# Command ids from components/sessions/core/session_service_commands.cc
CMD_SET_TAB_WINDOW              = 0
CMD_SET_TAB_INDEX_IN_WINDOW     = 2
CMD_NAV_PATH_PRUNED_FROM_BACK   = 5
CMD_UPDATE_TAB_NAVIGATION       = 6
CMD_SET_SELECTED_NAV_INDEX      = 7
CMD_TAB_CLOSED                  = 16
CMD_WINDOW_CLOSED               = 17
CMD_NAV_PATH_PRUNED             = 24   # tab_id, index, count

_SKIP_SCHEMES = ("chrome://", "brave://", "edge://", "about:", "chrome-extension://",
                 "devtools://", "file://", "data:", "javascript:")


def _read_pickle_string(buf: bytes, off: int) -> tuple[str, int]:
    (n,) = struct.unpack_from("<i", buf, off)
    off += 4
    if n < 0 or off + n > len(buf):
        raise ValueError("bad string")
    s = buf[off:off + n].decode("utf-8", errors="replace")
    off += (n + 3) & ~3          # pickle pads to 4 bytes
    return s, off


def parse_session(data: bytes) -> list[str]:
    """Return open-tab URLs (http/https only), ordered by window then tab index."""
    if len(data) < 8 or data[:4] != b"SNSS":
        return []
    tabs: dict[int, dict] = {}
    closed_tabs: set[int] = set()
    closed_windows: set[int] = set()

    def tab(tid: int) -> dict:
        return tabs.setdefault(tid, {"navs": {}, "sel": None, "win": None, "idx": 0, "order": len(tabs)})

    off = 8
    while off + 3 <= len(data):
        (size,) = struct.unpack_from("<H", data, off)
        if size == 0 or off + 2 + size > len(data):
            break
        cmd = data[off + 2]
        p = data[off + 3: off + 2 + size]
        off += 2 + size
        try:
            if cmd == CMD_UPDATE_TAB_NAVIGATION and len(p) >= 16:
                # pickle: uint32 payload_len, int32 tab_id, int32 index, string url, ...
                _, tid, idx = struct.unpack_from("<Iii", p, 0)
                url, _ = _read_pickle_string(p, 12)
                tab(tid)["navs"][idx] = url
            elif cmd == CMD_SET_SELECTED_NAV_INDEX and len(p) >= 8:
                tid, idx = struct.unpack_from("<ii", p, 0)
                tab(tid)["sel"] = idx
            elif cmd == CMD_SET_TAB_WINDOW and len(p) >= 8:
                wid, tid = struct.unpack_from("<ii", p, 0)
                tab(tid)["win"] = wid
            elif cmd == CMD_SET_TAB_INDEX_IN_WINDOW and len(p) >= 8:
                tid, idx = struct.unpack_from("<ii", p, 0)
                tab(tid)["idx"] = idx
            elif cmd == CMD_NAV_PATH_PRUNED_FROM_BACK and len(p) >= 8:
                tid, count = struct.unpack_from("<ii", p, 0)
                t = tab(tid)
                t["navs"] = {i: u for i, u in t["navs"].items() if i < count}
            elif cmd == CMD_NAV_PATH_PRUNED and len(p) >= 12:
                tid, index, count = struct.unpack_from("<iii", p, 0)
                t = tab(tid)
                kept = {}
                for i, u in t["navs"].items():
                    if i < index:
                        kept[i] = u
                    elif i >= index + count:
                        kept[i - count] = u
                t["navs"] = kept
            elif cmd == CMD_TAB_CLOSED and len(p) >= 4:
                closed_tabs.add(struct.unpack_from("<i", p, 0)[0])
            elif cmd == CMD_WINDOW_CLOSED and len(p) >= 4:
                closed_windows.add(struct.unpack_from("<i", p, 0)[0])
        except (struct.error, ValueError):
            continue

    open_tabs = []
    for tid, t in tabs.items():
        if tid in closed_tabs or (t["win"] is not None and t["win"] in closed_windows):
            continue
        if not t["navs"]:
            continue
        sel = t["sel"] if t["sel"] in t["navs"] else max(t["navs"])
        url = t["navs"][sel]
        if not url.startswith(("http://", "https://")) or url.startswith(_SKIP_SCHEMES):
            continue
        open_tabs.append((t["win"] or 0, t["idx"], t["order"], url))
    open_tabs.sort()
    seen: set[str] = set()
    return [u for *_, u in open_tabs if not (u in seen or seen.add(u))]


def current_session_file(profile_dir: Path) -> Path | None:
    """Newest live-session file (never the Tabs_* recently-closed list)."""
    sessions = profile_dir / "Sessions"
    candidates = list(sessions.glob("Session_*")) if sessions.exists() else []
    legacy = profile_dir / "Current Session"
    if legacy.exists():
        candidates.append(legacy)
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.stat().st_mtime)


def read_open_tabs(profile_dir: Path) -> list[str]:
    f = current_session_file(profile_dir)
    if not f:
        return []
    try:
        return parse_session(f.read_bytes())
    except OSError:
        return []
