"""
Deep Work AI — Time Travel page (lives inside the Hub)
======================================================
A timeline of your saved moments. For the selected one it shows what you were
doing: activity, focus, repo/branch, file, changed files, browser tabs and
your note — so you know exactly where you're going before it restores.

Two ways in:
  * the dial — the service moves the selection (data/timetravel.json) and
    restores when you stop turning;
  * the Hub sidebar — browse with the mouse wheel / ↑ ↓, Enter or click restores; the dial browses, a dial press or Resume restores.

100% local: reads data/*.db read-only.
  python -m deepworkai.ui.timetravel [--demo]   (opens the Hub on this page)
"""

from __future__ import annotations

import argparse
import json
import socket
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget)

from deepworkai.ui import hub
from deepworkai.ui.hub import (ACTIVITY, SYS, T, Badge, HatchCard, Icon, big, capsule, card, clear, font,
                                label, overline, _q)

from deepworkai.service.paths import DATA_DIR as DATA  # noqa: E402
STATE = DATA / "timetravel.json"
COMMIT_MS = 2500
VISIBLE = 7                       # rows shown on the rail around the selection

SOURCE_LABEL = {"auto": "Auto-saved", "hardware": "Saved by you", "meeting": "Before a meeting",
                "focus": "Focus started"}


# ── Data ──────────────────────────────────────────────────────────────────────
def _when(ts: str) -> tuple[str, str]:
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return ts, ""
    mins = int((datetime.now() - dt).total_seconds() // 60)
    clock = dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() != datetime.now().date():
        clock = dt.strftime("%a ") + clock
    if mins < 1:
        ago = "just now"
    elif mins < 60:
        ago = f"{mins} min ago"
    elif mins < 1440:
        ago = f"{mins // 60} h {mins % 60} min ago" if mins % 60 else f"{mins // 60} h ago"
    else:
        ago = f"{mins // 1440} d ago"
    return clock, ago


def _window_lines(windows: list) -> list[str]:
    """'Brave · YouTube', 'Code · app.py - my-repo' — one line per open window."""
    out = []
    for w in windows:
        app = (w.get("process") or "").removesuffix(".exe").removesuffix(".EXE")
        app = app[:1].upper() + app[1:]
        title = (w.get("title") or "").strip()
        if app.lower() in ("deepworkai", "explorer") and title == "Program Manager":
            continue                                    # the desktop, not a window you opened
        line = f"{app} · {title[:48]}" if title else app
        if line not in out:
            out.append(line)
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _domain(url: str) -> str:
    try:
        u = urlparse(url)
        path = u.path.strip("/").split("/")
        return (u.netloc.replace("www.", "") + ("/" + "/".join(path[:2]) if path[0] else ""))[:48]
    except Exception:
        return url[:48]


class Moments:
    """Snapshot details, parsed once and cached."""
    def __init__(self, demo: bool = False):
        self.demo = demo
        self.cache: dict[str, dict] = {}

    def get(self, cid: str) -> dict:
        if cid in self.cache:
            return self.cache[cid]
        m = self._demo(cid) if self.demo else self._load(cid)
        if len(self.cache) >= 120:                 # bounded: never grows with history
            self.cache.pop(next(iter(self.cache)))
        self.cache[cid] = m
        return m

    def _load(self, cid: str) -> dict:
        rows = _q(DATA / "capsules.db",
                  "SELECT name, timestamp, workspace_json FROM capsules WHERE id=?", (cid,))
        if not rows:
            return {"id": cid, "ts": "", "source": "", "activity": "idle"}
        r = rows[0]
        try:
            snap = json.loads(r["workspace_json"])
        except ValueError:
            snap = {}
        ctx = snap.get("_context") or {}
        git = snap.get("git") or {}
        tabs = [t.get("url", "") if isinstance(t, dict) else str(t)
                for v in (snap.get("browsers") or {}).values() for t in v]
        try:                                   # tabs locked at save time: readable once the browser closed
            from deepworkai.service.deep_restore_core import _tabs_from_session_file
            for files in (snap.get("pending_tabs") or {}).values():
                for e in files if isinstance(files, list) else [files]:
                    f, size = (e["file"], e.get("size")) if isinstance(e, dict) else (e, None)
                    tabs += [t["url"] for t in (_tabs_from_session_file(f, size) or [])]
        except Exception:
            pass
        apps = sorted({w.get("process", "").replace(".exe", "").title()
                       for w in snap.get("windows", []) if w.get("process")})
        activity, focus = ctx.get("activity"), ctx.get("focus_score")
        if not activity:                       # older snapshot: look up what the engine saw then
            near = _q(DATA / "intelligence.db",
                      "SELECT activity, focus_score FROM state_log WHERE ts <= ? ORDER BY ts DESC LIMIT 1",
                      (r["timestamp"],))
            if near:
                activity, focus = near[0]["activity"], near[0]["focus_score"]
        return {
            "id": cid, "ts": r["timestamp"], "source": r["name"],
            "activity": activity or "idle", "focus": focus,
            "repo": ctx.get("repo") or "", "branch": ctx.get("branch") or git.get("branch") or "",
            "file": ctx.get("file") or "",
            "changed": (ctx.get("changed_files") or git.get("changed_files") or [])[:4],
            "tabs": [_domain(u) for u in (tabs or ctx.get("tabs") or [])][:4],
            "n_tabs": len(tabs), "apps": apps[:6], "n_windows": len(snap.get("windows", [])),
            "windows": _window_lines(snap.get("windows", []))[:8],
            "note": ctx.get("next_step") or "",
        }

    def _demo(self, cid: str) -> dict:
        i = int(cid)
        base = [
            ("debugging", 81, "payments-api", "fix/null-check", "processor.py", "Add regression test for empty card token",
             ["src/payments/processor.py", "tests/test_processor.py"], ["github.com/acme/payments-api", "stackoverflow.com/questions"]),
            ("coding", 74, "payments-api", "fix/null-check", "card_token.py", "Null-check token before charge",
             ["src/payments/card_token.py"], ["docs.stripe.com/api"]),
            ("reviewing", 58, "web-app", "main", "PR #412", "Leave review on retry logic",
             [], ["github.com/acme/web-app/pull/412"]),
            ("communicating", 22, "", "", "", "", [], []),
            ("researching", 49, "infra", "feat/redis-cache", "cache.tf", "Compare TTL strategies",
             ["infra/cache.tf"], ["redis.io/docs", "developer.hashicorp.com/terraform"]),
            ("coding", 88, "infra", "feat/redis-cache", "cache_client.py", "Wire cache into orders API",
             ["src/cache_client.py", "src/orders/api.py", "tests/test_cache.py"], ["github.com/acme/infra"]),
        ]
        a = base[i % len(base)]
        ts = (datetime.now() - timedelta(minutes=12 + i * 23)).isoformat()
        return {"id": cid, "ts": ts, "source": ["auto", "hardware", "auto", "meeting", "auto", "hardware"][i % 6],
                "activity": a[0], "focus": a[1], "repo": a[2], "branch": a[3], "file": a[4], "note": a[5],
                "changed": a[6], "tabs": a[7], "n_tabs": len(a[7]) + 2,
                "apps": ["Code", "Brave", "Windowsterminal"], "n_windows": 5}


def _send(cmd: str) -> str:
    """Send an authenticated command to the local service."""
    try:
        key = (DATA / ".session_key").read_text().strip()
    except OSError:
        return ""
    try:
        with socket.create_connection(("127.0.0.1", 57321), timeout=2) as s:
            s.sendall(f"@{key} {cmd}\n".encode())
            return s.recv(512).decode(errors="ignore")
    except OSError:
        return ""


def recent_ids(limit: int = 40) -> list[str]:
    return [r["id"] for r in _q(DATA / "capsules.db",
                                "SELECT id FROM capsules ORDER BY timestamp DESC LIMIT ?", (limit,))]


# ── Widgets ───────────────────────────────────────────────────────────────────
class Rail(QWidget):
    """Vertical timeline: dots on a line, the selection highlighted."""
    ROW = 54

    def __init__(self, on_click):
        super().__init__()
        self.rows: list[dict] = []          # [{"key", "time", "ago", "title", "color", "selected"}]
        self.on_click = on_click
        self.setMinimumWidth(250)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_rows(self, rows):
        self.rows = rows
        self.setFixedHeight(max(1, len(rows)) * self.ROW)
        self.update()

    def mousePressEvent(self, e):
        i = int(e.position().y() // self.ROW)
        if 0 <= i < len(self.rows) and self.rows[i]["key"] is not None:
            self.on_click(self.rows[i]["key"])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = 18
        if len(self.rows) > 1:
            p.setPen(QPen(T["track"], 2))
            p.drawLine(QPointF(x, self.ROW / 2), QPointF(x, self.ROW * (len(self.rows) - 0.5)))
        for i, r in enumerate(self.rows):
            cy = i * self.ROW + self.ROW / 2
            col = QColor(r["color"])
            if r["selected"]:
                bg = QColor(T["text"]); bg.setAlpha(18)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg)
                p.drawRoundedRect(QRectF(2, i * self.ROW + 3, self.width() - 4, self.ROW - 6), 12, 12)
                halo = QColor(col); halo.setAlpha(60)
                p.setBrush(halo); p.drawEllipse(QPointF(x, cy), 10, 10)
            p.setPen(QPen(QColor(T["window"]), 2.5)); p.setBrush(col)
            p.drawEllipse(QPointF(x, cy), 6 if r["selected"] else 4.5, 6 if r["selected"] else 4.5)
            p.setPen(QColor(T["text"] if r["selected"] else T["text2"]))
            p.setFont(font(13.5, QFont.Weight.DemiBold if r["selected"] else QFont.Weight.Medium))
            p.drawText(QRectF(x + 20, i * self.ROW + 8, self.width() - x - 26, 20),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, r["time"])
            p.setPen(QColor(T["text3"]))
            p.setFont(font(11.5))
            p.drawText(QRectF(x + 20, i * self.ROW + 27, self.width() - x - 26, 18),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(r["title"], Qt.TextElideMode.ElideRight,
                                                  int(self.width() - x - 30)))


class Countdown(QWidget):
    def __init__(self):
        super().__init__()
        self.frac, self.color = 0.0, QColor(T["text"])
        self.setFixedHeight(3)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(T["track"])
        p.drawRoundedRect(QRectF(0, 0, self.width(), 4), 2, 2)
        if self.frac > 0:
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(0, 0, self.width() * self.frac, 4), 2, 2)


# ── Page ──────────────────────────────────────────────────────────────────────
class TimelinePage(QWidget):
    """Embedded in the Hub. `on_finish(result)` is called after a dial session ends."""

    def __init__(self, demo: bool = False, demo_index: int | None = None, on_finish=None):
        super().__init__()
        self.demo, self.on_finish = demo, on_finish
        self.moments = Moments(demo)
        self.local = {"ids": [], "index": -1}          # sidebar browsing (no dial)
        self.state: dict = {}
        if demo:
            self.state = {"index": 1 if demo_index is None else demo_index,
                          "ids": [str(i) for i in range(12)], "open": True, "updated": time.time()}
        self._mtime = 0.0
        self._finishing_until = 0.0
        self._last_sel = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        body = QVBoxLayout(self); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(14)
        # time is shown big inside the card — no duplicate header
        self.when = QLabel(); self.ago = QLabel()

        main = QHBoxLayout(); main.setSpacing(18)
        self.rail = Rail(self._click)
        railbox = QVBoxLayout(); railbox.addWidget(self.rail); railbox.addStretch()
        main.addLayout(railbox, 0)
        self.detail = HatchCard(32, 10); self.dl = self.detail.lay
        main.addWidget(self.detail, 1)
        body.addLayout(main, 1)

        self.bar = Countdown()
        body.addWidget(self.bar)
        foot = QHBoxLayout()
        self.hint = label("", 12.5, QFont.Weight.Medium, T["text2"])
        self.keys = label("", 11.5, color=T["text3"])
        foot.addWidget(self.hint); foot.addStretch(); foot.addWidget(self.keys)
        body.addLayout(foot)

    # ── modes ─────────────────────────────────────────────────────────────────
    def dial_active(self) -> bool:
        return bool(self.state.get("open")) or bool(self._finishing_until)

    def view(self) -> tuple[list[str], int]:
        if self.dial_active() or self.demo:
            return self.state.get("ids", []), self.state.get("index", -1)
        return self.local["ids"], self.local["index"]

    def refresh(self):
        """Called when the page is shown from the sidebar."""
        if not self.dial_active() and not self.demo:
            self.local["ids"] = recent_ids()
            self.local["index"] = min(self.local["index"], len(self.local["ids"]) - 1)
        self._last_sel = None
        self.poll()

    # ── polling (cheap: one stat() per tick) ──────────────────────────────────
    def read_state(self) -> bool:
        """Returns True if a new dial state arrived."""
        if self.demo:
            return False
        try:
            m = STATE.stat().st_mtime
        except OSError:
            return False
        if m == self._mtime:
            return False
        self._mtime = m
        try:
            self.state = json.loads(STATE.read_text())
        except (OSError, ValueError):
            return False
        return True

    def poll(self):
        fresh = self.read_state()
        st = self.state
        now = time.time()
        if fresh and st.get("result"):
            self._finish(st)
        if self._finishing_until and now > self._finishing_until:
            self._finishing_until = 0.0
            if self.on_finish:
                self.on_finish(st.get("result", ""))
            self._last_sel = None
        ids, idx = self.view()
        sel = (idx, tuple(ids), self.dial_active())
        if sel != self._last_sel:
            self._last_sel = sel
            self._render(ids, idx)
        self._update_footer(now)

    def _update_footer(self, now: float):
        if self._finishing_until:
            return
        if self.dial_active() and not self.demo or (self.demo and self.state.get("open")):
            idx = self.state.get("index", -1)
            elapsed = (now - self.state.get("updated", now)) * 1000
            self.keys.setText("Dial ← back · → towards now · press the dial or Resume to restore · Esc cancels")
            if idx >= 0:
                self.bar.frac = min(1.0, elapsed / COMMIT_MS)
                left = max(0.0, (COMMIT_MS - elapsed) / 1000)
                self.hint.setText(f"Restoring this moment in {left:.1f}s…" if left > 0 else "Restoring…")
            else:
                self.bar.frac = 0
                self.hint.setText("You're at Now. Turn left to go back.")
        else:
            self.bar.frac = 0
            self.keys.setText("Scroll or ↑ ↓ to browse · Enter or click to restore")
            ids, idx = self.view()
            self.hint.setText("Pick a moment to go back to." if ids else "")
        self.bar.update()

    # ── rendering ─────────────────────────────────────────────────────────────
    def _render(self, ids: list[str], idx: int):
        rows = [{"key": None, "time": "Now", "title": "Stay where you are", "color": SYS["green"],
                 "selected": idx < 0}]
        start = max(0, min(idx - VISIBLE // 2, len(ids) - (VISIBLE - 1)))
        for j in range(start, min(len(ids), start + VISIBLE - 1)):
            m = self.moments.get(ids[j])
            name, _, color = ACTIVITY.get(m["activity"], ACTIVITY["idle"])
            clock, _ = _when(m["ts"])
            what = " · ".join(x for x in (name, m.get("repo") or m.get("file")) if x)
            rows.append({"key": j, "time": clock, "title": what, "color": color, "selected": j == idx})
        self.rail.set_rows(rows)

        clear(self.dl)
        P, P2 = T["on_primary"], T["on_primary2"]
        if idx < 0 or idx >= len(ids):
            self.when.setText("Now")
            self.ago.setText(_plural(len(ids), "saved moment") if ids else "")
            self.dl.addWidget(capsule("Time travel", on_primary=True))
            self.dl.addSpacing(8)
            self.dl.addWidget(big("Now", 76, P))
            try:                                   # live: what's open right now
                from deepworkai.service.deep_restore_core import enum_windows
                now = _window_lines(enum_windows())[:8]
            except Exception:
                now = []
            if now:
                self.dl.addSpacing(4)
                self.dl.addWidget(overline("Open right now", P2))
                for ln in now:
                    self.dl.addWidget(label(ln, 14, color=P, wrap=True))
            self.dl.addStretch()
            self.dl.addWidget(label(
                "Turn the dial left, scroll, or press ↓ to walk back through your day. Press the dial or Resume to restore. "
                "Each stop shows what you were doing." if ids else
                "No saved moments yet. They're captured automatically every 10 minutes while you "
                "work, when you start focusing, and when you save your spot.", 14, color=P2, wrap=True))
            return

        m = self.moments.get(ids[idx])
        clock, ago = _when(m["ts"])
        self.when.setText(clock)
        self.ago.setText(ago)
        name = ACTIVITY.get(m["activity"], ACTIVITY["idle"])[0]
        self.bar.color = QColor(T["text"])

        top = QHBoxLayout(); top.setSpacing(8)
        top.addWidget(capsule(f"You were {name.lower()}" if m["activity"] != "idle" else "Away", on_primary=True))
        top.addWidget(capsule(SOURCE_LABEL.get(m["source"], (m["source"] or "saved").title()), on_primary=True))
        top.addStretch()
        self.dl.addLayout(top)
        self.dl.addSpacing(8)
        hm, _, ampm = clock.rpartition(" ")
        row = QHBoxLayout(); row.setSpacing(10)
        row.addWidget(big(hm or clock, 76, P))
        if hm:
            row.addWidget(label(ampm, 18, QFont.Weight.Normal, P2), 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch()
        if m.get("focus") is not None:
            f = QVBoxLayout(); f.setSpacing(0)
            v = big(str(m["focus"]), 34, P); v.setAlignment(Qt.AlignmentFlag.AlignRight); f.addWidget(v)
            k = overline("focus", P2); k.setAlignment(Qt.AlignmentFlag.AlignRight); f.addWidget(k)
            row.addLayout(f)
        self.dl.addLayout(row)
        meta = " · ".join(x for x in (m.get("repo"), m.get("branch")) if x)
        counts = " · ".join(x for x in (_plural(m["n_windows"], "window") if m.get("n_windows") else "",
                                        _plural(m["n_tabs"], "tab") if m.get("n_tabs") else "") if x)
        self.dl.addWidget(label(" — ".join(x for x in (ago, meta, counts) if x), 14, color=P2, wrap=True))
        self.dl.addSpacing(10)

        def section(title, lines):
            if not lines:
                return
            self.dl.addSpacing(4)
            self.dl.addWidget(overline(title, P2))
            for ln in lines:
                self.dl.addWidget(label(ln, 14, color=P, wrap=True))

        section("Your note", [m["note"]] if m.get("note") else [])
        section("Open windows", m.get("windows") or ([", ".join(m["apps"])] if m.get("apps") else []))
        section("Tabs", m.get("tabs", []))
        self.dl.addStretch()

    def _finish(self, st):
        if st.get("result") == "restore":
            m = self.moments.get(st.get("restored", ""))
            clock, _ = _when(m.get("ts", ""))
            self.hint.setText(f"✓ Restoring your workspace from {clock}")
            self.bar.frac, self.bar.color = 1.0, QColor(T["text"])
            self.bar.update()
            self._finishing_until = time.time() + 1.4
        else:
            self._finishing_until = time.time() + 0.05

    # ── local browsing (sidebar) ──────────────────────────────────────────────
    def _move(self, delta: int):
        if self.dial_active() or self.demo:
            return
        n = len(self.local["ids"])
        self.local["index"] = max(-1, min(n - 1, self.local["index"] + delta))
        self.poll()

    def _restore_selected(self):
        ids, idx = self.view()
        if 0 <= idx < len(ids) and not self.demo:
            m = self.moments.get(ids[idx])
            clock, _ = _when(m.get("ts", ""))
            self.hint.setText(f"✓ Restoring your workspace from {clock}")
            _send(f"TRAVEL_GO:{ids[idx]}")

    def _click(self, row_index: int):
        if self.dial_active() and not self.demo:
            ids, _ = self.view()
            _send(f"TRAVEL_GO:{ids[row_index]}")
            return
        self.local["index"] = row_index
        self.poll()
        self._restore_selected()

    def wheelEvent(self, e):
        self._move(1 if e.angleDelta().y() < 0 else -1)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Down, Qt.Key.Key_J):
            self._move(1)
        elif k in (Qt.Key.Key_Up, Qt.Key.Key_K):
            self._move(-1)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._restore_selected()
        else:
            super().keyPressEvent(e)


def main(argv=None):
    """Compatibility entry point: open the Hub on the Time Travel page."""
    args = list(argv if argv is not None else sys.argv[1:])
    return hub.main(["--tab", "timeline"] + args)


if __name__ == "__main__":
    sys.exit(main())
