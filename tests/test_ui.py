"""UI stress: the one Hub window stays fast with lots of real-shaped data."""
import json
import sqlite3
import time
from datetime import datetime, timedelta

import pytest

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture()
def hub_env(qapp, tmp_path, monkeypatch):
    from deepworkai.ui import hub, timetravel
    monkeypatch.setattr(hub, "DATA", tmp_path)
    monkeypatch.setattr(timetravel, "DATA", tmp_path)
    monkeypatch.setattr(timetravel, "STATE", tmp_path / "timetravel.json")
    hub._apply_theme("dark", QApplication.instance())
    return hub, timetravel, tmp_path


def _notifications(db, n):
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE notifications (id TEXT PRIMARY KEY, source TEXT, title TEXT, body TEXT,
                 url TEXT, sender TEXT, channel TEXT, priority TEXT, confidence REAL,
                 arrived_at TEXT, reviewed INTEGER, held INTEGER)""")
    for i in range(n):
        c.execute("INSERT INTO notifications VALUES (?,?,?,?,?,?,?,?,?,?,0,1)",
                  (f"n{i}", ["slack", "github", "jira"][i % 3], f"<b>Title {i}</b>", "body " * 30,
                   "https://x.io", f"user{i}", "chan", ["HIGH", "MEDIUM", "LOW"][i % 3], 0.8,
                   (datetime.now() - timedelta(minutes=i)).isoformat()))
    c.commit(); c.close()


def _capsules(db, n):
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE capsules (id TEXT PRIMARY KEY, name TEXT, timestamp TEXT, workspace_json TEXT, summary TEXT)")
    for i in range(n):
        snap = {"windows": [{"process": "code.exe"}] * 4, "browsers": {"brave.exe": [{"url": f"https://g.com/{i}"}]},
                "git": {"branch": "main"}, "_context": {"activity": "coding", "focus_score": 70,
                                                        "repo": "api", "file": f"f{i}.py", "next_step": "n"}}
        c.execute("INSERT INTO capsules VALUES (?,?,?,?,?)",
                  (f"id{i}", "auto", (datetime.now() - timedelta(minutes=10 * i)).isoformat(), json.dumps(snap), ""))
    c.commit(); c.close()


def test_inbox_with_300_notifications_is_fast(hub_env):
    hub, _, data = hub_env
    _notifications(data / "notifications.db", 300)
    w = hub.Hub("focus", persistent=True)
    t = time.perf_counter()
    w.present("inbox"); QApplication.processEvents()
    assert time.perf_counter() - t < 2.0
    inbox = w.pages["inbox"]
    assert len(inbox.items) == 200                     # capped query — UI never drowns
    for _ in range(20):                                # rapid filter flipping
        for k in ("HIGH", "LOW", "ALL"):
            inbox.set_filter(k)
    QApplication.processEvents()


def test_timeline_survives_rapid_dial_updates(hub_env):
    hub, tt, data = hub_env
    _capsules(data / "capsules.db", 40)
    w = hub.Hub("focus", persistent=True)
    page = w.pages["timeline"]
    ids = [f"id{i}" for i in range(40)]
    t = time.perf_counter()
    for k in range(200):                               # 200 dial ticks as fast as possible
        st = {"index": (k * 7) % 41 - 1, "ids": ids, "open": True, "updated": time.time() + k}
        (data / "timetravel.json").write_text(json.dumps(st))
        page._mtime = 0
        page.poll()
    assert (time.perf_counter() - t) / 200 < 0.05      # < 50 ms per tick incl. re-render
    (data / "timetravel.json").write_text(json.dumps({**st, "open": False, "result": "cancel"}))
    page._mtime = 0; page.poll()
    time.sleep(0.1); page.poll()
    assert not page.dial_active()


def test_sidebar_browsing_uses_real_snapshots(hub_env):
    hub, tt, data = hub_env
    _capsules(data / "capsules.db", 5)
    w = hub.Hub("timeline", persistent=True)
    page = w.pages["timeline"]
    page.refresh()
    assert page.local["ids"] == [f"id{i}" for i in range(5)]
    page._move(1); page._move(1)
    ids, idx = page.view()
    assert idx == 1 and page.moments.get(ids[idx])["file"] == "f1.py"


def test_hub_commands_from_service(hub_env):
    hub, _, data = hub_env
    w = hub.Hub("focus", persistent=True)
    (data / "ui_cmd.json").write_text(json.dumps({"action": "show", "tab": "inbox", "ts": time.time()}))
    w._fast(); QApplication.processEvents()
    assert w.isVisible() and w.stack.currentWidget() is w.pages["inbox"]
    w.close()                                          # persistent: hides, doesn't quit
    assert w.isHidden()
    (data / "ui_cmd.json").write_text(json.dumps({"action": "show", "tab": "focus", "focus_note": True,
                                                  "ts": time.time() + 1}))
    w._fast(); QApplication.processEvents()
    assert w.stack.currentWidget() is w.pages["focus"]


def test_note_is_saved_from_hub(hub_env):
    hub, _, data = hub_env
    w = hub.Hub("focus", persistent=True)
    fp = w.pages["focus"]
    fp.note.setPlainText("ship the fix"); fp._save_note()
    assert (data / "next_step.txt").read_text() == "ship the fix"
