"""
Deep Work AI — Time Travel overlay
==================================
Shown while you turn the dial. Lists your saved moments as a timeline and, for
the selected one, shows what you were doing: activity, focus, repo/branch,
file, changed files, browser tabs and your note — so you know exactly where
you are going before it restores.

Driven by the service through data/timetravel.json (selection index + ids).
Click a moment to restore it, Esc to cancel. 100% local: reads data/*.db.

  pythonw -m deepworkai.ui.timetravel [--demo] [--theme auto|light|dark]
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
from deepworkai.ui.hub import (ACTIVITY, SYS, T, Icon, capsule, card, clear, font, label, _q)

DATA = ROOT / "data"
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


def _send(cmd: str):
    try:
        with socket.create_connection(("127.0.0.1", 57321), timeout=2) as s:
            s.sendall((cmd + "\n").encode())
            s.recv(256)
    except OSError:
        pass


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
        self.frac, self.color = 0.0, QColor(SYS["blue"])
        self.setFixedHeight(4)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(T["track"])
        p.drawRoundedRect(QRectF(0, 0, self.width(), 4), 2, 2)
        if self.frac > 0:
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(0, 0, self.width() * self.frac, 4), 2, 2)


# ── Window ────────────────────────────────────────────────────────────────────
class TimeTravel(QWidget):
    SHADOW = 18

    def __init__(self, demo: bool = False, demo_index: int = 1):
        super().__init__()
        self.demo = demo
        self.moments = Moments(demo)
        self.state = {"index": demo_index, "ids": [str(i) for i in range(12)], "open": True,
                      "updated": time.time()} if demo else {}
        self._mtime = 0.0
        self._closing_at = 0.0

        self.setWindowTitle("Time Travel")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(840 + 2 * self.SHADOW, 560 + 2 * self.SHADOW)

        outer = QVBoxLayout(self)
        s = self.SHADOW
        outer.setContentsMargins(s, s - 4, s, s + 4)
        root = QFrame(); root.setObjectName("root")
        outer.addWidget(root)
        body = QVBoxLayout(root); body.setContentsMargins(28, 22, 28, 20); body.setSpacing(16)

        head = QHBoxLayout(); head.setSpacing(12)
        head.addWidget(Icon("rewind", SYS["blue"], 40, 1.5, tile=True))
        tl = QVBoxLayout(); tl.setSpacing(0)
        tl.addWidget(label("Time Travel", 12, QFont.Weight.DemiBold, T["text2"], caps=True))
        self.when = label("", 26, QFont.Weight.Bold, display=True)
        tl.addWidget(self.when)
        head.addLayout(tl); head.addStretch()
        self.ago = label("", 15, QFont.Weight.Medium, T["text2"])
        head.addWidget(self.ago, 0, Qt.AlignmentFlag.AlignBottom)
        body.addLayout(head)

        main = QHBoxLayout(); main.setSpacing(20)
        self.rail = Rail(self._go)
        railbox = QVBoxLayout(); railbox.addWidget(self.rail); railbox.addStretch()
        main.addLayout(railbox, 0)
        self.detail, self.dl = card(22, 12)
        main.addWidget(self.detail, 1)
        body.addLayout(main, 1)

        foot = QVBoxLayout(); foot.setSpacing(8)
        self.bar = Countdown()
        foot.addWidget(self.bar)
        hint = QHBoxLayout()
        self.hint = label("", 12.5, QFont.Weight.Medium, T["text2"])
        hint.addWidget(self.hint); hint.addStretch()
        hint.addWidget(label("Turn ← back · → towards now · stop to restore · click to jump · Esc to cancel",
                             11.5, color=T["text3"]))
        foot.addLayout(hint)
        body.addLayout(foot)

        self.setStyleSheet(hub.qss())
        self._last_sel = None
        self._poll()
        self.t = QTimer(self); self.t.timeout.connect(self._poll); self.t.start(33)

    # state & rendering
    def _poll(self):
        if not self.demo:
            try:
                m = STATE.stat().st_mtime
                if m != self._mtime:
                    self._mtime = m
                    self.state = json.loads(STATE.read_text())
            except (OSError, ValueError):
                pass
        st = self.state
        if self._closing_at and time.time() > self._closing_at:
            self.close(); return
        if st.get("result") and not self._closing_at:
            self._finish(st); return
        if not self.demo and st and not st.get("open") and not st.get("result"):
            self.close(); return
        if not self.demo and st and time.time() - st.get("updated", 0) > 30:
            self.close(); return                 # orphaned overlay safety net
        sel = (st.get("index"), tuple(st.get("ids", [])))
        if sel != self._last_sel:
            self._last_sel = sel
            self._render()
        elapsed = (time.time() - st.get("updated", time.time())) * 1000
        idx = st.get("index", -1)
        if not self._closing_at:
            if idx >= 0:
                self.bar.frac = min(1.0, elapsed / COMMIT_MS)
                left = max(0.0, (COMMIT_MS - elapsed) / 1000)
                self.hint.setText(f"Restoring this moment in {left:.1f}s…" if left > 0 else "Restoring…")
            else:
                self.bar.frac = 0
                self.hint.setText("You're at Now. Turn left to go back.")
            self.bar.update()

    def _render(self):
        st = self.state
        ids, idx = st.get("ids", []), st.get("index", -1)
        # Rail: "Now" + snapshots, windowed around the selection
        rows = [{"key": None, "time": "Now", "title": "Stay where you are", "color": SYS["green"],
                 "selected": idx < 0}]
        start = max(0, min(idx - VISIBLE // 2, len(ids) - (VISIBLE - 1)))
        for j in range(start, min(len(ids), start + VISIBLE - 1)):
            m = self.moments.get(ids[j])
            name, _, color = ACTIVITY.get(m["activity"], ACTIVITY["idle"])
            clock, _ = _when(m["ts"])
            what = " · ".join(x for x in (name, m.get("repo") or m.get("file")) if x)
            rows.append({"key": ids[j], "time": clock, "title": what, "color": color, "selected": j == idx})
        self.rail.set_rows(rows)

        clear(self.dl)
        if idx < 0 or idx >= len(ids):
            self.when.setText("Now")
            self.ago.setText(f"{len(ids)} saved moments" if ids else "")
            self.dl.addStretch()
            ic = QHBoxLayout(); ic.addStretch(); ic.addWidget(Icon("clock", SYS["green"], 52, 1.4, tile=True)); ic.addStretch()
            self.dl.addLayout(ic)
            for txt, px, wt, col in (("You're in the present", 20, QFont.Weight.DemiBold, None),
                                     ("Turn the dial to the left to walk back through your day. "
                                      "Each stop shows what you were doing." if ids else
                                      "No saved moments yet. They're captured automatically while you "
                                      "work, when you start focusing, and when you save your spot.",
                                      13, QFont.Weight.Normal, T["text2"])):
                l = label(txt, px, wt, col, display=px > 15, wrap=True)
                l.setAlignment(Qt.AlignmentFlag.AlignCenter); self.dl.addWidget(l)
            self.dl.addStretch()
            return

        m = self.moments.get(ids[idx])
        clock, ago = _when(m["ts"])
        self.when.setText(clock)
        self.ago.setText(ago)
        name, icon, color = ACTIVITY.get(m["activity"], ACTIVITY["idle"])
        self.bar.color = QColor(color)

        top = QHBoxLayout(); top.setSpacing(12)
        top.addWidget(Icon(icon, color, 44, 1.5, tile=True))
        tc = QVBoxLayout(); tc.setSpacing(2)
        tc.addWidget(label(f"You were {name.lower()}" if m["activity"] != "idle" else "Away / idle",
                           22, QFont.Weight.DemiBold, display=True))
        meta = " · ".join(x for x in (m.get("repo"), m.get("branch")) if x)
        tc.addWidget(label(meta or SOURCE_LABEL.get(m["source"], "Saved moment"), 13, color=T["text2"]))
        top.addLayout(tc, 1)
        if m.get("focus") is not None:
            f = QVBoxLayout(); f.setSpacing(0)
            v = label(str(m["focus"]), 26, QFont.Weight.DemiBold, color, display=True)
            v.setAlignment(Qt.AlignmentFlag.AlignRight); f.addWidget(v)
            k = label("focus", 11, QFont.Weight.Medium, T["text3"]); k.setAlignment(Qt.AlignmentFlag.AlignRight)
            f.addWidget(k); top.addLayout(f)
        self.dl.addLayout(top)

        tags = QHBoxLayout(); tags.setSpacing(6)
        tags.addWidget(capsule(SOURCE_LABEL.get(m["source"], m["source"].title() or "Saved"), SYS["gray"]))
        if m.get("n_windows"):
            tags.addWidget(capsule(f"{m['n_windows']} windows", SYS["indigo"]))
        if m.get("n_tabs"):
            tags.addWidget(capsule(f"{m['n_tabs']} tabs", SYS["teal"]))
        tags.addStretch()
        self.dl.addLayout(tags)

        def section(ic, title, lines, col):
            if not lines:
                return
            self.dl.addSpacing(2)
            r = QHBoxLayout(); r.setSpacing(7)
            r.addWidget(Icon(ic, col, 14, 1.7))
            r.addWidget(label(title, 11, QFont.Weight.DemiBold, T["text3"], caps=True)); r.addStretch()
            self.dl.addLayout(r)
            for ln in lines:
                self.dl.addWidget(label(ln, 13.5, color=T["text"], wrap=True))

        section("pencil", "Your note", [m["note"]] if m.get("note") else [], SYS["orange"])
        changed = m.get("changed", [])
        own = m.get("file")
        files = ([own] if own and not any(c.endswith(own) for c in changed) else []) + changed
        section("code", "Files", files[:4], SYS["blue"])
        section("book", "Tabs", m.get("tabs", []), SYS["teal"])
        if not (m.get("note") or files or m.get("tabs")) and m.get("apps"):
            section("folder", "Open apps", [", ".join(m["apps"])], SYS["gray"])
        self.dl.addStretch()

    def _finish(self, st):
        if st.get("result") == "restore":
            m = self.moments.get(st.get("restored", ""))
            clock, _ = _when(m.get("ts", ""))
            self.hint.setText(f"✓ Restoring your workspace from {clock}")
            self.bar.frac, self.bar.color = 1.0, QColor(SYS["green"])
            self.bar.update()
            self._closing_at = time.time() + 1.4
        else:
            self._closing_at = time.time() + 0.05

    def closeEvent(self, e):
        # Tool windows don't trigger quit-on-last-window; end the process ourselves.
        super().closeEvent(e)
        QApplication.quit()

    def _go(self, cid: str):
        if self.demo:
            return
        _send(f"TRAVEL_GO:{cid}")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            if not self.demo:
                _send("TRAVEL_CLOSE")
            self.close()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.SHADOW
        r = QRectF(self.rect()).adjusted(s, s - 4, -s, -s - 4)
        for i in range(s, 0, -1):
            a = int(55 * (1 - i / s) ** 2)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, a // 3))
            p.drawRoundedRect(r.adjusted(-i, -i + 6, i, i + 6), 20 + i, 20 + i)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deep Work AI — Time Travel")
    ap.add_argument("--theme", default="auto", choices=["auto", "light", "dark"])
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--demo-index", type=int, default=1)
    ap.add_argument("--screenshot", default="", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    hub._apply_theme(a.theme, app)
    w = TimeTravel(a.demo, a.demo_index)
    if a.screenshot:
        w.show(); app.processEvents()
        w.grab().save(a.screenshot)
        return 0
    scr = app.primaryScreen().availableGeometry()
    w.move(scr.center() - w.rect().center())
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
