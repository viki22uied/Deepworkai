"""Tests for the live-session tab reader (the fix for stale Brave tabs on restore)."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deepworkai" / "service"))
import chromium_session as cs


def rec(cmd, payload):
    return struct.pack("<HB", len(payload) + 1, cmd) + payload


def nav(tid, idx, url):
    u = url.encode()
    body = struct.pack("<ii", tid, idx) + struct.pack("<i", len(u)) + u + b"\0" * (-len(u) % 4)
    return rec(cs.CMD_UPDATE_TAB_NAVIGATION, struct.pack("<I", len(body)) + body)


def build(*records):
    return b"SNSS" + struct.pack("<i", 3) + b"".join(records)


def test_only_open_tabs_at_selected_entry():
    data = build(
        rec(cs.CMD_SET_TAB_WINDOW, struct.pack("<ii", 1, 10)),
        nav(10, 0, "https://old-history.example/"),           # back history, not current
        nav(10, 1, "https://github.com/me/repo"),
        rec(cs.CMD_SET_SELECTED_NAV_INDEX, struct.pack("<ii", 10, 1)),
        rec(cs.CMD_SET_TAB_WINDOW, struct.pack("<ii", 1, 11)),
        rec(cs.CMD_SET_TAB_INDEX_IN_WINDOW, struct.pack("<ii", 11, 1)),
        nav(11, 0, "https://closed-months-ago.example/"),
        rec(cs.CMD_TAB_CLOSED, struct.pack("<iiq", 11, 0, 0)),   # closed → must not return
        rec(cs.CMD_SET_TAB_WINDOW, struct.pack("<ii", 1, 12)),
        rec(cs.CMD_SET_TAB_INDEX_IN_WINDOW, struct.pack("<ii", 12, 2)),
        nav(12, 0, "https://docs.python.org/3/"),
        rec(cs.CMD_SET_TAB_WINDOW, struct.pack("<ii", 2, 13)),
        nav(13, 0, "https://in-closed-window.example/"),
        rec(cs.CMD_WINDOW_CLOSED, struct.pack("<iiq", 2, 0, 0)),
        rec(cs.CMD_SET_TAB_WINDOW, struct.pack("<ii", 1, 14)),
        rec(cs.CMD_SET_TAB_INDEX_IN_WINDOW, struct.pack("<ii", 14, 3)),
        nav(14, 0, "brave://newtab/"),
    )
    assert cs.parse_session(data) == ["https://github.com/me/repo", "https://docs.python.org/3/"]


def test_garbage_is_safe():
    assert cs.parse_session(b"not a session") == []
    assert cs.parse_session(build(b"\xff\xff\x06")) == []


def test_ignores_recently_closed_file(tmp_path):
    s = tmp_path / "Sessions"
    s.mkdir()
    (s / "Tabs_999").write_bytes(build(nav(1, 0, "https://stale.example/")))
    (s / "Session_1").write_bytes(build(nav(1, 0, "https://live.example/")))
    assert cs.read_open_tabs(tmp_path) == ["https://live.example/"]
