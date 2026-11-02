"""
Deep Work AI — Hub
==================
One fast, clean window for everything you look at:

  • Focus     — what you're doing now, focus score, "where was I", next step
  • Inbox     — notifications the AI held back, by priority, with why
  • Insights  — your best focus hours, deep-work time, who interrupts you

100% local: reads the SQLite files in <repo>/data directly. No network,
no telemetry. Starts in well under a second.

Usage:
  pythonw -m deepworkai.ui.hub [--tab focus|inbox|insights] [--filter HIGH] [--demo]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"

from PyQt6.QtCore import Qt, QTimer, QRectF, QPoint
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget, QSizePolicy, QGraphicsDropShadowEffect,
)

# ── Design tokens ─────────────────────────────────────────────────────────────
C = {
    "bg":       "#0d0f14",
    "panel":    "#141821",
    "card":     "#1a1f2b",
    "card_hi":  "#212838",
    "border":   "#262d3d",
    "text":     "#e8ecf4",
    "muted":    "#8b93a7",
    "dim":      "#5b6377",
    "accent":   "#7c5cff",
    "accent2":  "#22d3ee",
    "high":     "#ff5d6c",
    "medium":   "#ffb547",
    "low":      "#6b7a99",
    "good":     "#34d399",
}
PRIORITY = {"HIGH": C["high"], "MEDIUM": C["medium"], "LOW": C["low"]}
SOURCE_ICON = {"slack": "💬", "github": "🐙", "jira": "🎫", "manual": "📝", "teams": "👥"}
ACTIVITY = {
    "coding":        ("⌨️", "Coding",        C["accent"]),
    "debugging":     ("🐞", "Debugging",     C["high"]),
    "reviewing":     ("🔍", "Reviewing",     C["accent2"]),
    "researching":   ("📚", "Researching",   C["medium"]),
    "communicating": ("💬", "Communicating", C["low"]),
    "meeting":       ("📅", "In a meeting",  C["low"]),
    "idle":          ("🌙", "Idle",          C["dim"]),
}

QSS = f"""
* {{ font-family: 'Segoe UI Variable', 'Segoe UI', 'Inter', sans-serif; color: {C['text']}; }}
#root {{ background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 16px; }}
#sidebar {{ background: {C['panel']}; border-top-left-radius: 16px; border-bottom-left-radius: 16px; }}
QPushButton#nav {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 10px;
    font-size: 13px; font-weight: 600; color: {C['muted']}; background: transparent;
}}
QPushButton#nav:hover {{ background: {C['card']}; color: {C['text']}; }}
QPushButton#nav:checked {{ background: {C['accent']}; color: white; }}
QPushButton#chip {{
    padding: 6px 14px; border-radius: 14px; border: 1px solid {C['border']};
    background: {C['card']}; color: {C['muted']}; font-size: 12px; font-weight: 600;
}}
QPushButton#chip:checked {{ color: white; border-color: transparent; }}
QPushButton#ghost {{
    padding: 6px 12px; border-radius: 8px; border: 1px solid {C['border']};
    background: transparent; color: {C['muted']}; font-size: 12px; font-weight: 600;
}}
QPushButton#ghost:hover {{ background: {C['card_hi']}; color: {C['text']}; }}
QPushButton#primary {{
    padding: 6px 12px; border-radius: 8px; border: none;
    background: {C['accent']}; color: white; font-size: 12px; font-weight: 600;
}}
QPushButton#primary:hover {{ background: #8f74ff; }}
QPushButton#close {{ border: none; color: {C['dim']}; font-size: 16px; background: transparent; }}
QPushButton#close:hover {{ color: {C['high']}; }}
#card {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 14px; }}
#card:hover {{ background: {C['card_hi']}; }}
QLabel#h1 {{ font-size: 22px; font-weight: 700; }}
QLabel#h2 {{ font-size: 14px; font-weight: 700; }}
QLabel#muted {{ color: {C['muted']}; font-size: 12px; }}
QLabel#dim {{ color: {C['dim']}; font-size: 11px; }}
QLabel#big {{ font-size: 28px; font-weight: 700; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


# ── Data (local SQLite only) ──────────────────────────────────────────────────
def _q(db: Path, sql: str, args=()) -> list[dict]:
    if not db.exists():
        return []
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
        c.close()
        return rows
    except sqlite3.Error:
        return []


def _ago(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        s = int((datetime.now() - datetime.fromisoformat(iso)).total_seconds())
    except ValueError:
        return ""
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


class Data:
    def __init__(self, demo: bool = False):
        self.demo = demo

    def focus(self) -> dict:
        if self.demo:
            return {"activity": "debugging", "focus_score": 78, "deep_minutes": 42,
                    "repo": "payments-api", "branch": "fix/null-check",
                    "where": "debugging in payments-api@fix/null-check on processor.py (42m deep, focus 81)",
                    "where_ago": _ago((datetime.now() - timedelta(minutes=12)).isoformat()),
                    "anchor": "anchored processor.py:214",
                    "next_step": "Add regression test for empty card token",
                    "timeline": [62, 70, 74, 80, 85, 81, 40, 55, 72, 78]}
        st = _q(DATA / "intelligence.db",
                "SELECT activity, focus_score, ts FROM state_log ORDER BY ts DESC LIMIT 40")
        ctx = _q(DATA / "intelligence.db", "SELECT * FROM auto_context ORDER BY ts DESC LIMIT 1")
        git = _q(DATA / "activity.db",
                 "SELECT details FROM events WHERE event_type='git_context' ORDER BY timestamp DESC LIMIT 1")
        g = {}
        if git:
            try:
                g = json.loads(git[0]["details"] or "{}")
            except ValueError:
                pass
        note = ""
        nf = DATA / "next_step.txt"
        if nf.exists():
            note = nf.read_text(encoding="utf-8", errors="ignore").strip()
        cur = st[0] if st else {"activity": "idle", "focus_score": 0}
        deep = 0
        for r in st:
            if r["focus_score"] >= 60:
                deep += 0.5
            else:
                break
        return {
            "activity": cur["activity"], "focus_score": cur["focus_score"], "deep_minutes": int(deep),
            "repo": g.get("repo", ""), "branch": g.get("branch", ""),
            "where": ctx[0]["summary"] if ctx else "",
            "where_ago": _ago(ctx[0]["ts"]) if ctx else "",
            "anchor": ctx[0]["anchor"] if ctx else "",
            "next_step": note,
            "timeline": [r["focus_score"] for r in reversed(st[:20])],
        }

    def inbox(self) -> list[dict]:
        if self.demo:
            now = datetime.now()
            mk = lambda m: (now - timedelta(minutes=m)).isoformat()
            return [
                {"id": "1", "source": "jira", "priority": "HIGH", "confidence": .97, "decision": "DELIVER",
                 "title": "PROD-1923 — API gateway 500s on /orders", "sender": "incident-bot",
                 "channel": "incidents", "body": "All order requests failing since 14:32.", "arrived_at": mk(3), "url": "https://example.com"},
                {"id": "2", "source": "github", "priority": "MEDIUM", "confidence": .81, "decision": "HOLD",
                 "title": "Review requested: Add retry to webhook sender", "sender": "maria",
                 "channel": "", "body": "Small PR, ~40 lines.", "arrived_at": mk(18), "url": ""},
                {"id": "3", "source": "slack", "priority": "MEDIUM", "confidence": .66, "decision": "HOLD",
                 "title": "Can you look at the staging config when free?", "sender": "dev-ops",
                 "channel": "platform", "body": "", "arrived_at": mk(25), "url": ""},
                {"id": "4", "source": "slack", "priority": "LOW", "confidence": .9, "decision": "BATCH",
                 "title": "Lunch order for Friday 🍕", "sender": "office",
                 "channel": "random", "body": "", "arrived_at": mk(40), "url": ""},
            ]
        rows = _q(DATA / "notifications.db",
                  "SELECT * FROM notifications WHERE reviewed=0 ORDER BY arrived_at DESC LIMIT 200")
        dec = {r["notif_id"]: r["decision"] for r in _q(
            DATA / "intelligence.db", "SELECT notif_id, decision FROM decisions ORDER BY ts DESC LIMIT 500")}
        for r in rows:
            r["decision"] = dec.get(r["id"], "HOLD" if r.get("held") else "DELIVER")
        rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        rows.sort(key=lambda r: (rank.get(r.get("priority"), 1), r.get("arrived_at") or ""))
        return rows

    def dismiss(self, nid: str):
        if self.demo:
            return
        try:
            from deepworkai.features.notification_classifier import mark_reviewed
            mark_reviewed(nid)
        except Exception:
            pass

    def insights(self) -> dict:
        if self.demo:
            return {"best_hours": ["09:00", "10:00", "15:00"], "deep_minutes": 412,
                    "held": 37, "delivered": 9,
                    "interruptions": {"slack": 28, "github": 12, "jira": 6},
                    "hours": {h: v for h, v in zip(range(8, 19), [40, 72, 85, 80, 50, 35, 45, 66, 78, 60, 30])}}
        try:
            from deepworkai.features.workflow_intelligence import insights
            out = insights()
        except Exception:
            out = {"best_hours": [], "deep_minutes": 0, "held": 0, "delivered": 0, "interruptions": {}}
        since = (datetime.now() - timedelta(days=7)).isoformat()
        hours: dict[int, list[int]] = {}
        for r in _q(DATA / "intelligence.db",
                    "SELECT ts, focus_score FROM state_log WHERE ts >= ?", (since,)):
            hours.setdefault(datetime.fromisoformat(r["ts"]).hour, []).append(r["focus_score"])
        out["hours"] = {h: sum(v) / len(v) for h, v in sorted(hours.items())}
        return out


# ── Widgets ───────────────────────────────────────────────────────────────────
def label(text: str, obj: str = "", wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    l.setWordWrap(wrap)
    l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return l


def card(pad: int = 16) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(pad, pad, pad, pad)
    lay.setSpacing(6)
    return f, lay


class Ring(QWidget):
    """Focus-score ring."""
    def __init__(self, value: int, color: str, size: int = 132):
        super().__init__()
        self.value, self.color = max(0, min(100, value)), QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(10, 10, self.width() - 20, self.height() - 20)
        p.setPen(QPen(QColor(C["border"]), 10, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 0, 360 * 16)
        p.setPen(QPen(self.color, 10, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, -int(self.value / 100 * 360 * 16))
        p.setPen(QColor(C["text"]))
        p.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        p.drawText(r.adjusted(0, -10, 0, -10), Qt.AlignmentFlag.AlignCenter, str(self.value))
        p.setPen(QColor(C["muted"]))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        p.drawText(r.adjusted(0, 34, 0, 0), Qt.AlignmentFlag.AlignCenter, "FOCUS")


class Bars(QWidget):
    """Minimal bar chart (values 0-100) with optional labels."""
    def __init__(self, values: list[float], labels: list[str] | None = None, height: int = 90):
        super().__init__()
        self.values, self.labels = values, labels or []
        self.setMinimumHeight(height + (16 if self.labels else 0))
        self.h = height

    def paintEvent(self, _):
        if not self.values:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n, w = len(self.values), self.width()
        gap = 6
        bw = max(4, (w - gap * (n - 1)) / n)
        top = max(self.values) or 1
        for i, v in enumerate(self.values):
            bh = max(3, v / max(100, top) * self.h)
            x = i * (bw + gap)
            col = QColor(C["accent"] if v >= 60 else C["accent2"] if v >= 35 else C["low"])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, self.h - bh, bw, bh), 3, 3)
            if i < len(self.labels):
                p.setPen(QColor(C["dim"]))
                p.setFont(QFont("Segoe UI", 8))
                p.drawText(QRectF(x - 6, self.h + 2, bw + 12, 14), Qt.AlignmentFlag.AlignCenter, self.labels[i])


def chip_label(text: str, color: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"background: {color}22; color: {color}; border-radius: 9px;"
                    f"padding: 2px 9px; font-size: 11px; font-weight: 700;")
    return l


def scroll(inner: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setWidget(inner)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return s


def clear(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().hide()            # hide now; avoids ghost/flicker
            it.widget().deleteLater()
        elif it.layout():
            clear(it.layout())


# ── Pages ─────────────────────────────────────────────────────────────────────
class FocusPage(QWidget):
    def __init__(self, data: Data):
        super().__init__()
        self.data = data
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(14)
        self.refresh()

    def refresh(self):
        clear(self.lay)
        d = self.data.focus()
        icon, name, color = ACTIVITY.get(d["activity"], ACTIVITY["idle"])

        hero, h = card(20)
        row = QHBoxLayout()
        row.setSpacing(22)
        row.addWidget(Ring(d["focus_score"], color))
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(label("RIGHT NOW", "dim"))
        col.addWidget(label(f"{icon}  {name}", "h1"))
        ctx = " · ".join(x for x in [d["repo"] and f"📁 {d['repo']}",
                                     d["branch"] and f"🌿 {d['branch']}"] if x)
        col.addWidget(label(ctx or "No repository detected yet", "muted"))
        tags = QHBoxLayout()
        tags.setSpacing(6)
        deep = d["focus_score"] >= 60
        tags.addWidget(chip_label("DEEP FOCUS" if deep else "SHALLOW", C["good"] if deep else C["medium"]))
        if d["deep_minutes"]:
            tags.addWidget(chip_label(f"{d['deep_minutes']} MIN STREAK", C["accent2"]))
        tags.addStretch()
        col.addSpacing(6)
        col.addLayout(tags)
        col.addStretch()
        row.addLayout(col, 1)
        h.addLayout(row)
        self.lay.addWidget(hero)

        grid = QHBoxLayout()
        grid.setSpacing(14)
        w, wl = card()
        wl.addWidget(label("🧭  WHERE WAS I", "dim"))
        wl.addWidget(label(d["where"] or "Nothing captured yet — I'll save your spot automatically "
                           "when an interruption pulls you out of deep focus.", "h2" if d["where"] else "muted", True))
        if d["where_ago"]:
            wl.addWidget(label(f"Saved {d['where_ago']}  ·  {d['anchor']}", "dim", True))
        wl.addStretch()
        n, nl = card()
        nl.addWidget(label("📝  NEXT STEP", "dim"))
        nl.addWidget(label(d["next_step"] or "No note yet — press Journal on your keypad.",
                           "h2" if d["next_step"] else "muted", True))
        nl.addStretch()
        grid.addWidget(w, 3)
        grid.addWidget(n, 2)
        self.lay.addLayout(grid)

        t, tl = card()
        tl.addWidget(label("FOCUS · LAST 10 MINUTES", "dim"))
        tl.addWidget(Bars(d["timeline"] or [0], height=70))
        self.lay.addWidget(t)
        self.lay.addStretch()


class InboxPage(QWidget):
    def __init__(self, data: Data, flt: str = "ALL"):
        super().__init__()
        self.data, self.flt = data, flt or "ALL"
        self.items: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.chips: dict[str, QPushButton] = {}
        for key in ("ALL", "HIGH", "MEDIUM", "LOW"):
            b = QPushButton(key.title())
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, k=key: self.set_filter(k))
            self.chips[key] = b
            bar.addWidget(b)
        bar.addStretch()
        clr = QPushButton("Clear all")
        clr.setObjectName("ghost")
        clr.setCursor(Qt.CursorShape.PointingHandCursor)
        clr.clicked.connect(self.clear_all)
        bar.addWidget(clr)
        root.addLayout(bar)
        inner = QWidget()
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(10)
        root.addWidget(scroll(inner), 1)
        self.refresh()

    def refresh(self):
        self.items = self.data.inbox()
        self.render()

    def set_filter(self, k: str):
        self.flt = k
        self.render()

    def render(self):
        counts = {k: sum(1 for i in self.items if i.get("priority") == k) for k in PRIORITY}
        for k, b in self.chips.items():
            n = len(self.items) if k == "ALL" else counts[k]
            b.setText(f"{k.title()}  {n}")
            b.setChecked(k == self.flt)
            col = C["accent"] if k == "ALL" else PRIORITY[k]
            b.setStyleSheet(f"QPushButton#chip:checked {{ background: {col}; }}")
        clear(self.list)
        shown = [i for i in self.items if self.flt == "ALL" or i.get("priority") == self.flt]
        if not shown:
            e = label("✨  You're all caught up", "h2")
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s = label("Nothing is waiting for you. Stay in the zone.", "muted")
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list.addSpacing(70)
            self.list.addWidget(e)
            self.list.addWidget(s)
        for it in shown:
            self.list.addWidget(self.make_card(it))
        self.list.addStretch()

    def make_card(self, it: dict) -> QFrame:
        pr = it.get("priority", "MEDIUM")
        pc = PRIORITY.get(pr, C["medium"])
        f, lay = card(14)
        f.setStyleSheet(f"#card {{ border-left: 4px solid {pc}; }}")
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel(SOURCE_ICON.get(it.get("source", ""), "📣")))
        top.addWidget(chip_label(pr, pc))
        dec = it.get("decision", "")
        why = {"HOLD": ("HELD · until a break", C["accent2"]),
               "BATCH": ("BATCHED · digest", C["low"]),
               "DELIVER": ("DELIVERED", C["good"])}.get(dec)
        if why:
            top.addWidget(chip_label(*why))
        top.addStretch()
        top.addWidget(label(_ago(it.get("arrived_at")), "dim"))
        lay.addLayout(top)
        lay.addWidget(label(it.get("title") or "(no title)", "h2", True))
        body = (it.get("body") or "").strip()
        if body:
            lay.addWidget(label(body[:220] + ("…" if len(body) > 220 else ""), "muted", True))
        bot = QHBoxLayout()
        meta = "  ·  ".join(x for x in [it.get("sender") and f"@{it['sender']}",
                                        it.get("channel") and f"#{it['channel']}",
                                        f"{int(float(it.get('confidence') or 0) * 100)}% sure"] if x)
        bot.addWidget(label(meta, "dim"))
        bot.addStretch()
        if it.get("url"):
            o = QPushButton("Open ↗")
            o.setObjectName("primary")
            o.setCursor(Qt.CursorShape.PointingHandCursor)
            o.clicked.connect(lambda _, u=it["url"]: webbrowser.open(u))
            bot.addWidget(o)
        d = QPushButton("Done")
        d.setObjectName("ghost")
        d.setCursor(Qt.CursorShape.PointingHandCursor)
        d.clicked.connect(lambda _, i=it["id"]: self.dismiss(i))
        bot.addWidget(d)
        lay.addLayout(bot)
        return f

    def dismiss(self, nid: str):
        self.data.dismiss(nid)
        self.items = [i for i in self.items if i["id"] != nid]
        self.render()

    def clear_all(self):
        for i in [i for i in self.items if self.flt == "ALL" or i.get("priority") == self.flt]:
            self.data.dismiss(i["id"])
        self.items = [i for i in self.items if not (self.flt == "ALL" or i.get("priority") == self.flt)]
        self.render()


class InsightsPage(QWidget):
    def __init__(self, data: Data):
        super().__init__()
        self.data = data
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(14)
        self.refresh()

    def refresh(self):
        clear(self.lay)
        d = self.data.insights()
        tiles = QHBoxLayout()
        tiles.setSpacing(14)
        hrs = d["deep_minutes"] // 60
        for title, value, color in [
            ("DEEP WORK · 7 DAYS", f"{hrs}h {d['deep_minutes'] % 60}m", C["accent"]),
            ("INTERRUPTIONS HELD", str(d["held"]), C["accent2"]),
            ("LET THROUGH", str(d["delivered"]), C["good"]),
        ]:
            f, l = card()
            l.addWidget(label(title, "dim"))
            v = label(value, "big")
            v.setStyleSheet(f"color: {color};")
            l.addWidget(v)
            tiles.addWidget(f)
        self.lay.addLayout(tiles)

        f, l = card()
        l.addWidget(label("⏰  WHEN YOU FOCUS BEST", "dim"))
        best = d.get("best_hours") or []
        l.addWidget(label(", ".join(best) if best else "Collecting data — check back after a day of work.",
                          "h2" if best else "muted"))
        hours = d.get("hours") or {}
        if hours:
            l.addSpacing(6)
            l.addWidget(Bars(list(hours.values()), [f"{h}" for h in hours], height=80))
        self.lay.addWidget(f)

        f, l = card()
        l.addWidget(label("📨  WHO INTERRUPTS YOU", "dim"))
        ints = d.get("interruptions") or {}
        total = sum(ints.values()) or 1
        if not ints:
            l.addWidget(label("No interruptions recorded yet.", "muted"))
        for src, n in ints.items():
            r = QHBoxLayout()
            r.addWidget(label(f"{SOURCE_ICON.get(src, '📣')}  {src.title()}", "h2"), 0)
            bar = QFrame()
            bar.setFixedHeight(8)
            bar.setStyleSheet(f"background: {C['accent']}; border-radius: 4px;")
            bar.setFixedWidth(max(8, int(260 * n / total)))
            r.addStretch()
            r.addWidget(bar)
            r.addWidget(label(f"  {n}", "muted"))
            l.addLayout(r)
        self.lay.addWidget(f)
        foot = label("🔒  All of this is computed and stored on this PC only. Nothing leaves your machine.", "dim", True)
        self.lay.addWidget(foot)
        self.lay.addStretch()


# ── Window ────────────────────────────────────────────────────────────────────
class Hub(QWidget):
    TABS = [("focus", "🎯   Focus"), ("inbox", "📥   Inbox"), ("insights", "📊   Insights")]

    def __init__(self, tab: str = "focus", flt: str = "", demo: bool = False):
        super().__init__()
        self.setWindowTitle("Deep Work AI")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(860, 600)
        self._drag: QPoint | None = None
        data = Data(demo)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        root = QFrame()
        root.setObjectName("root")
        sh = QGraphicsDropShadowEffect(blurRadius=30, xOffset=0, yOffset=8)
        sh.setColor(QColor(0, 0, 0, 160))
        root.setGraphicsEffect(sh)
        outer.addWidget(root)
        body = QHBoxLayout(root)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(190)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 20, 14, 16)
        sl.setSpacing(4)
        brand = label("◆ Deep Work", "h2")
        brand.setStyleSheet(f"color: {C['accent']}; font-size: 16px; font-weight: 800;")
        sl.addWidget(brand)
        sl.addWidget(label("Focus OS", "dim"))
        sl.addSpacing(18)
        self.stack = QStackedWidget()
        self.pages = {"focus": FocusPage(data), "inbox": InboxPage(data, flt),
                      "insights": InsightsPage(data)}
        self.navs: dict[str, QPushButton] = {}
        for key, text in self.TABS:
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, k=key: self.show_tab(k))
            sl.addWidget(b)
            self.navs[key] = b
            self.stack.addWidget(self.pages[key])
        sl.addStretch()
        sl.addWidget(label("🔒 Local · Offline", "dim"))
        body.addWidget(side)

        main = QVBoxLayout()
        main.setContentsMargins(24, 16, 20, 20)
        main.setSpacing(14)
        head = QHBoxLayout()
        self.title = label("", "h1")
        head.addWidget(self.title)
        head.addStretch()
        self.clock = label("", "dim")
        head.addWidget(self.clock)
        x = QPushButton("✕")
        x.setObjectName("close")
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.clicked.connect(self.close)
        head.addWidget(x)
        main.addLayout(head)
        main.addWidget(self.stack, 1)
        body.addLayout(main, 1)

        self.setStyleSheet(QSS)
        self.show_tab(tab if tab in self.pages else "focus")
        self.clock.setText(datetime.now().strftime("%a %d %b · %H:%M"))
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(15_000)                                     # cheap local refresh

    def show_tab(self, key: str):
        for k, b in self.navs.items():
            b.setChecked(k == key)
        self.stack.setCurrentWidget(self.pages[key])
        self.title.setText(dict(self.TABS)[key].split("   ")[1])

    def _tick(self):
        self.clock.setText(datetime.now().strftime("%a %d %b · %H:%M"))
        page = self.stack.currentWidget()
        if hasattr(page, "refresh") and not isinstance(page, InboxPage):
            page.refresh()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        elif e.key() in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
            self.show_tab(self.TABS[e.key() - Qt.Key.Key_1][0])

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _):
        self._drag = None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deep Work AI Hub")
    ap.add_argument("--tab", default="focus", choices=["focus", "inbox", "insights"])
    ap.add_argument("--filter", default="", help="HIGH|MEDIUM|LOW (inbox)")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--screenshot", default="", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv)
    w = Hub(a.tab, a.filter.upper(), a.demo)
    if a.screenshot:
        w.show()
        app.processEvents()
        w.grab().save(a.screenshot)
        return 0
    scr = app.primaryScreen().availableGeometry()
    w.move(scr.center() - w.rect().center())
    w.show()
    w.activateWindow()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
