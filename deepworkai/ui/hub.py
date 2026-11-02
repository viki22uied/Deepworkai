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

from PyQt6.QtCore import Qt, QTimer, QRectF, QPoint, QPointF
from PyQt6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QGuiApplication,
                         QLinearGradient, QPainter, QPainterPath, QPen)
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

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
                    "timeline": [62, 70, 74, 80, 85, 81, 40, 55, 72, 78],
                    "rewind": {"last_ide_file": "processor.py",
                               "changed_files": ["src/payments/processor.py", "tests/test_processor.py"],
                               "browser_tabs": ["https://github.com/acme/payments-api/pull/412",
                                                "https://stackoverflow.com/questions/1234/null-card-token"]},
                    "radar": {"ci": "fail", "prs": 2, "behind": 3, "branch": "fix/null-check"},
                    "palette": [{"label": l} for l in ("Tests", "Dev", "Build", "Push", "Pull", "Logs")]}
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
            "rewind": self._rewind(),
            "radar": self._radar(),
            "palette": self._palette(),
        }

    @staticmethod
    def _rewind() -> dict:
        try:
            from deepworkai.features.cognitive_rewind import build_rewind_context
            c = build_rewind_context(minutes=30)
            return {"last_ide_file": c.get("last_ide_file") or "",
                    "changed_files": (c.get("git") or {}).get("changed_files", [])[:4],
                    "browser_tabs": c.get("browser_tabs", [])[:3]}
        except Exception:
            return {}

    @staticmethod
    def _radar() -> dict:
        f = DATA / "radar_state.json"
        try:
            return json.loads(f.read_text()) if f.exists() else {}
        except ValueError:
            return {}

    @staticmethod
    def _palette() -> list[dict]:
        try:
            from deepworkai.features.terminal_palette import load_palette
            return load_palette()
        except Exception:
            return []

    def run_palette(self, slot: int) -> str:
        if self.demo:
            return "demo"
        try:
            from deepworkai.features.terminal_palette import run_slot
            return run_slot(slot)
        except Exception as e:
            return str(e)

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


# ── Theme ─────────────────────────────────────────────────────────────────────
# Apple-style system palette. Light & dark; follows the OS by default.
DARK = {
    "window": "#151517", "sidebar": "#1c1c1f", "card": "#232327", "card2": "#1f1f23",
    "hover": "#2a2a2f", "line": "rgba(255,255,255,0.07)", "line_q": QColor(255, 255, 255, 18),
    "text": "#f5f5f7", "text2": "#a1a1a6", "text3": "#6e6e73", "track": QColor(255, 255, 255, 22),
    "sel": "rgba(255,255,255,0.08)", "seg": "#2c2c31", "seg_on": "#45454b",
}
LIGHT = {
    "window": "#f5f5f7", "sidebar": "#ebebef", "card": "#ffffff", "card2": "#fbfbfd",
    "hover": "#f2f2f5", "line": "rgba(0,0,0,0.06)", "line_q": QColor(0, 0, 0, 14),
    "text": "#1d1d1f", "text2": "#6e6e73", "text3": "#aeaeb2", "track": QColor(0, 0, 0, 16),
    "sel": "rgba(0,0,0,0.06)", "seg": "#e3e3e8", "seg_on": "#ffffff",
}
SYS = {"blue": "#0a84ff", "green": "#30d158", "orange": "#ff9f0a", "red": "#ff453a",
       "purple": "#bf5af2", "indigo": "#5e5ce6", "teal": "#64d2ff", "gray": "#8e8e93"}
T = dict(DARK)

PRIORITY = {"HIGH": SYS["red"], "MEDIUM": SYS["orange"], "LOW": SYS["gray"]}
SOURCE = {"slack": ("bubble", SYS["purple"]), "github": ("merge", SYS["indigo"]),
          "jira": ("ticket", SYS["blue"]), "teams": ("bubble", SYS["indigo"]),
          "manual": ("pencil", SYS["gray"])}
ACTIVITY = {
    "coding":        ("Coding",        "code",    SYS["blue"]),
    "debugging":     ("Debugging",     "bug",     SYS["red"]),
    "reviewing":     ("Reviewing",     "merge",   SYS["teal"]),
    "researching":   ("Researching",   "book",    SYS["orange"]),
    "communicating": ("Communicating", "bubble",  SYS["purple"]),
    "meeting":       ("In a meeting",  "clock",   SYS["indigo"]),
    "idle":          ("Idle",          "moon",    SYS["gray"]),
}
FONT_FAMILIES = ["Segoe UI Variable Display", "SF Pro Display", "Inter Display", "Inter", "Segoe UI"]
TEXT_FAMILIES = ["Segoe UI Variable Text", "SF Pro Text", "Inter", "Segoe UI"]


def font(px: float, weight=QFont.Weight.Normal, display: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES if display else TEXT_FAMILIES)
    f.setPixelSize(int(px))
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    if display and px >= 20:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98)
    return f


def qss() -> str:
    return f"""
    QWidget {{ color: {T['text']}; background: transparent; }}
    #root {{ background: {T['window']}; border-radius: 20px; border: 1px solid {T['line']}; }}
    #sidebar {{ background: {T['sidebar']}; border-top-left-radius: 20px;
                border-bottom-left-radius: 20px; border-right: 1px solid {T['line']}; }}
    #card {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {T['card']}, stop:1 {T['card2']});
             border: 1px solid {T['line']}; border-radius: 18px; }}
    QPushButton {{ border: none; }}
    QPushButton#nav {{ text-align: left; padding: 9px 12px 9px 40px; border-radius: 10px;
                       color: {T['text2']}; }}
    QPushButton#nav:hover {{ background: {T['sel']}; color: {T['text']}; }}
    QPushButton#nav:checked {{ background: {T['sel']}; color: {T['text']}; }}
    #segment {{ background: {T['seg']}; border-radius: 10px; }}
    QPushButton#seg {{ padding: 6px 14px; border-radius: 8px; color: {T['text2']}; }}
    QPushButton#seg:checked {{ background: {T['seg_on']}; color: {T['text']}; }}
    QPushButton#link {{ color: {SYS['blue']}; padding: 4px 6px; }}
    QPushButton#link:hover {{ color: #409cff; }}
    QPushButton#quiet {{ color: {T['text2']}; padding: 4px 6px; }}
    QPushButton#quiet:hover {{ color: {T['text']}; }}
    QPushButton#pill {{ background: {SYS['blue']}; color: white; padding: 6px 14px; border-radius: 14px; }}
    QPushButton#pill:hover {{ background: #409cff; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {T['line']}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
    """


# ── Vector icons (crisp at any scale, SF-Symbols-like strokes) ────────────────
def _icon_path(name: str) -> QPainterPath:
    p = QPainterPath()
    if name == "target":
        p.addEllipse(QPointF(10, 10), 7.5, 7.5); p.addEllipse(QPointF(10, 10), 4, 4)
        p.addEllipse(QPointF(10, 10), 0.8, 0.8)
    elif name == "tray":
        p.moveTo(3, 11); p.lineTo(5.5, 4); p.lineTo(14.5, 4); p.lineTo(17, 11)
        p.addRoundedRect(QRectF(3, 11, 14, 6), 2, 2)
        p.moveTo(3, 11); p.lineTo(7, 11); p.lineTo(8, 13); p.lineTo(12, 13); p.lineTo(13, 11); p.lineTo(17, 11)
    elif name == "chart":
        for x, h in ((4, 6), (8.5, 10), (13, 13)):
            p.addRoundedRect(QRectF(x, 17 - h, 3, h), 1.2, 1.2)
    elif name == "folder":
        p.moveTo(3, 6); p.lineTo(3, 15.5); p.quadTo(3, 16.5, 4, 16.5); p.lineTo(16, 16.5)
        p.quadTo(17, 16.5, 17, 15.5); p.lineTo(17, 8); p.quadTo(17, 7, 16, 7); p.lineTo(9.5, 7)
        p.lineTo(8, 5); p.lineTo(4, 5); p.quadTo(3, 5, 3, 6)
    elif name in ("branch", "merge"):
        p.addEllipse(QPointF(6, 4.5), 2, 2); p.addEllipse(QPointF(6, 15.5), 2, 2)
        p.addEllipse(QPointF(14, 8), 2, 2)
        p.moveTo(6, 6.5); p.lineTo(6, 13.5)
        p.moveTo(14, 10); p.cubicTo(14, 13, 8, 12, 6.5, 13.8)
    elif name == "compass":
        p.addEllipse(QPointF(10, 10), 7.5, 7.5)
        p.moveTo(13, 7); p.lineTo(11.2, 11.2); p.lineTo(7, 13); p.lineTo(8.8, 8.8); p.closeSubpath()
    elif name == "pencil":
        p.moveTo(4, 16); p.lineTo(5, 12.5); p.lineTo(13, 4.5); p.lineTo(15.5, 7); p.lineTo(7.5, 15)
        p.closeSubpath(); p.moveTo(11.5, 6); p.lineTo(14, 8.5)
    elif name == "lock":
        p.addRoundedRect(QRectF(4.5, 9, 11, 8), 2, 2)
        p.moveTo(7, 9); p.lineTo(7, 6.5); p.cubicTo(7, 2.5, 13, 2.5, 13, 6.5); p.lineTo(13, 9)
    elif name == "bubble":
        p.addRoundedRect(QRectF(3, 4, 14, 10), 4, 4)
        p.moveTo(6.5, 14); p.lineTo(5.5, 17); p.lineTo(9.5, 14)
    elif name == "ticket":
        p.moveTo(3, 6); p.lineTo(17, 6); p.lineTo(17, 8.5); p.cubicTo(15.5, 8.5, 15.5, 11.5, 17, 11.5)
        p.lineTo(17, 14); p.lineTo(3, 14); p.lineTo(3, 11.5); p.cubicTo(4.5, 11.5, 4.5, 8.5, 3, 8.5)
        p.closeSubpath()
    elif name == "code":
        p.moveTo(7, 6); p.lineTo(3, 10); p.lineTo(7, 14); p.moveTo(13, 6); p.lineTo(17, 10)
        p.lineTo(13, 14); p.moveTo(11, 4.5); p.lineTo(9, 15.5)
    elif name == "bug":
        p.addEllipse(QRectF(6, 6, 8, 11)); p.moveTo(10, 9); p.lineTo(10, 17)
        p.moveTo(6, 10); p.lineTo(3, 9); p.moveTo(6, 14); p.lineTo(3, 15)
        p.moveTo(14, 10); p.lineTo(17, 9); p.moveTo(14, 14); p.lineTo(17, 15)
        p.moveTo(8, 6.5); p.lineTo(7, 4); p.moveTo(12, 6.5); p.lineTo(13, 4)
    elif name == "book":
        p.moveTo(10, 5.5); p.cubicTo(8, 4, 5, 4, 3, 4.5); p.lineTo(3, 15.5); p.cubicTo(5, 15, 8, 15, 10, 16.5)
        p.cubicTo(12, 15, 15, 15, 17, 15.5); p.lineTo(17, 4.5); p.cubicTo(15, 4, 12, 4, 10, 5.5)
        p.lineTo(10, 16.5)
    elif name == "clock":
        p.addEllipse(QPointF(10, 10), 7.5, 7.5); p.moveTo(10, 5.5); p.lineTo(10, 10); p.lineTo(13, 12)
    elif name == "moon":
        p.moveTo(14.5, 13.5); p.cubicTo(9, 15, 5, 10, 8, 4.5); p.cubicTo(3, 6, 3, 15, 9.5, 16.5)
        p.cubicTo(12, 17, 14, 15.5, 14.5, 13.5)
    elif name == "terminal":
        p.addRoundedRect(QRectF(2.5, 4, 15, 12), 2.5, 2.5)
        p.moveTo(6, 8); p.lineTo(8.5, 10); p.lineTo(6, 12); p.moveTo(10, 12.5); p.lineTo(14, 12.5)
    elif name == "rewind":
        p.moveTo(4, 10); p.cubicTo(4, 4, 13, 2.5, 16, 8); p.moveTo(4, 10); p.lineTo(2.5, 7.5)
        p.moveTo(4, 10); p.lineTo(6.8, 8.6)
        p.moveTo(16, 12); p.cubicTo(14.5, 16, 8, 17.5, 5.5, 14)
    elif name == "radar":
        p.addEllipse(QPointF(10, 10), 7.5, 7.5); p.addEllipse(QPointF(10, 10), 4, 4)
        p.moveTo(10, 10); p.lineTo(15.3, 4.7)
    elif name == "close":
        p.moveTo(6, 6); p.lineTo(14, 14); p.moveTo(14, 6); p.lineTo(6, 14)
    elif name == "sparkle":
        p.moveTo(10, 3); p.cubicTo(10.5, 8, 12, 9.5, 17, 10); p.cubicTo(12, 10.5, 10.5, 12, 10, 17)
        p.cubicTo(9.5, 12, 8, 10.5, 3, 10); p.cubicTo(8, 9.5, 9.5, 8, 10, 3)
    return p


class Icon(QWidget):
    def __init__(self, name: str, color: str, size: int = 18, stroke: float = 1.6,
                 tile: bool = False):
        super().__init__()
        self.name, self.color, self.stroke, self.tile = name, QColor(color), stroke, tile
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        if self.tile:                                   # iOS-style tinted tile
            bg = QColor(self.color); bg.setAlpha(38)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg)
            p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.28, s * 0.28)
            p.translate(s * 0.2, s * 0.2); p.scale(s * 0.6 / 20, s * 0.6 / 20)
        else:
            p.scale(s / 20, s / 20)
        pen = QPen(self.color, self.stroke)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(_icon_path(self.name))


def label(text: str, px: float = 13, weight=QFont.Weight.Normal, color: str | None = None,
          display: bool = False, wrap: bool = False, caps: bool = False) -> QLabel:
    l = QLabel(text.upper() if caps else text)
    f = font(px, weight, display)
    if caps:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
    l.setFont(f)
    l.setStyleSheet(f"color: {color or T['text']};")
    l.setWordWrap(wrap)
    return l


def card(pad: int = 18, spacing: int = 8) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame(); f.setObjectName("card")
    lay = QVBoxLayout(f); lay.setContentsMargins(pad, pad, pad, pad); lay.setSpacing(spacing)
    return f, lay


def caption(icon: str, text: str, color: str) -> QHBoxLayout:
    r = QHBoxLayout(); r.setSpacing(7)
    r.addWidget(Icon(icon, color, 15, 1.7))
    r.addWidget(label(text, 11.5, QFont.Weight.DemiBold, T["text2"], caps=True))
    r.addStretch()
    return r


def capsule(text: str, color: str) -> QLabel:
    l = QLabel(text)
    l.setFont(font(11, QFont.Weight.DemiBold))
    c = QColor(color)
    l.setStyleSheet(f"color: {color}; background: rgba({c.red()},{c.green()},{c.blue()},0.14);"
                    "border-radius: 10px; padding: 3px 10px;")
    return l


class Ring(QWidget):
    """Activity-ring style focus gauge with a gradient arc."""
    def __init__(self, value: int, color: str, size: int = 148):
        super().__init__()
        self.value, self.color = max(0, min(100, int(value))), QColor(color)
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = 13
        r = QRectF(w, w, self.width() - 2 * w, self.height() - 2 * w)
        p.setPen(QPen(T["track"], w, cap=Qt.PenCapStyle.RoundCap))
        p.drawEllipse(r)
        if self.value:
            g = QConicalGradient(r.center(), 90)
            light = QColor(self.color).lighter(135)
            g.setColorAt(0.0, light); g.setColorAt(1 - self.value / 100, self.color)
            g.setColorAt(1.0, light)
            p.setPen(QPen(QBrush(g), w, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(r, 90 * 16, -int(self.value / 100 * 360 * 16))
        p.setPen(QColor(T["text"]))
        p.setFont(font(40, QFont.Weight.DemiBold, True))
        p.drawText(r.adjusted(0, -12, 0, -12), Qt.AlignmentFlag.AlignCenter, str(self.value))
        p.setPen(QColor(T["text2"]))
        p.setFont(font(11.5, QFont.Weight.Medium))
        p.drawText(r.adjusted(0, 40, 0, 0), Qt.AlignmentFlag.AlignCenter, "Focus")


class AreaChart(QWidget):
    """Smooth line with gradient fill (values 0-100)."""
    def __init__(self, values: list[float], color: str, height: int = 92):
        super().__init__()
        self.values, self.color = values, QColor(color)
        self.setFixedHeight(height)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height() - 6
        pen = QPen(T["line_q"], 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        for frac in (0.0, 0.5, 1.0):
            y = 3 + h * frac
            p.drawLine(QPointF(0, y), QPointF(w, y))
        vals = self.values if len(self.values) > 1 else [0, 0]
        pts = [QPointF(i * w / (len(vals) - 1), 3 + h - max(0, min(100, v)) / 100 * h)
               for i, v in enumerate(vals)]
        line = QPainterPath(pts[0])
        for a, b in zip(pts, pts[1:]):
            mx = (a.x() + b.x()) / 2
            line.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
        fill = QPainterPath(line)
        fill.lineTo(w, h + 3); fill.lineTo(0, h + 3); fill.closeSubpath()
        g = QLinearGradient(0, 0, 0, h)
        top = QColor(self.color); top.setAlpha(90)
        bot = QColor(self.color); bot.setAlpha(0)
        g.setColorAt(0, top); g.setColorAt(1, bot)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g)); p.drawPath(fill)
        pen = QPen(self.color, 2.4); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(line)
        last = pts[-1]
        p.setPen(QPen(QColor(T["card"]), 2.5)); p.setBrush(self.color)
        p.drawEllipse(last, 4.5, 4.5)


class HourBars(QWidget):
    """Screen-Time-style hourly bars; best hours highlighted."""
    def __init__(self, hours: dict[int, float], best: set[int], height: int = 120):
        super().__init__()
        self.hours, self.best = hours, best
        self.setFixedHeight(height)

    def paintEvent(self, _):
        if not self.hours:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        keys = list(self.hours)
        n, w, h = len(keys), self.width(), self.height() - 22
        gap = 8
        bw = (w - gap * (n - 1)) / n
        for i, k in enumerate(keys):
            v = max(0, min(100, self.hours[k]))
            bh = max(4, v / 100 * h)
            x = i * (bw + gap)
            col = QColor(SYS["blue"] if k in self.best else T["text3"])
            if k not in self.best:
                col.setAlpha(110)
            g = QLinearGradient(0, h - bh, 0, h)
            g.setColorAt(0, col.lighter(115)); g.setColorAt(1, col)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(g))
            p.drawRoundedRect(QRectF(x, h - bh, bw, bh), min(6, bw / 2), min(6, bw / 2))
            p.setPen(QColor(T["text3"]))
            p.setFont(font(10.5, QFont.Weight.Medium))
            hr = k % 12 or 12
            p.drawText(QRectF(x - 8, h + 6, bw + 16, 14), Qt.AlignmentFlag.AlignCenter,
                       f"{hr}{'a' if k < 12 else 'p'}")


def scroll(inner: QWidget) -> QScrollArea:
    s = QScrollArea(); s.setWidgetResizable(True); s.setWidget(inner)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    s.setFrameShape(QFrame.Shape.NoFrame)
    return s


def clear(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().hide(); it.widget().deleteLater()
        elif it.layout():
            clear(it.layout())


# ── Pages ─────────────────────────────────────────────────────────────────────
class Page(QWidget):
    def __init__(self, data: Data):
        super().__init__()
        self.data = data
        inner = QWidget()
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(0, 0, 6, 8)
        self.lay.setSpacing(16)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll(inner))
        self.refresh()

    def refresh(self):
        clear(self.lay); self.build(); self.lay.addStretch()


class FocusPage(Page):
    def build(self):
        d = self.data.focus()
        name, icon, color = ACTIVITY.get(d["activity"], ACTIVITY["idle"])

        hero, h = card(22)
        row = QHBoxLayout(); row.setSpacing(26)
        row.addWidget(Ring(d["focus_score"], color))
        col = QVBoxLayout(); col.setSpacing(6)
        col.addStretch()
        col.addWidget(label("Right now", 12, QFont.Weight.DemiBold, T["text2"], caps=True))
        t = QHBoxLayout(); t.setSpacing(10)
        t.addWidget(Icon(icon, color, 34, 1.5, tile=True))
        t.addWidget(label(name, 30, QFont.Weight.DemiBold, display=True)); t.addStretch()
        col.addLayout(t)
        meta = QHBoxLayout(); meta.setSpacing(6)
        if d["repo"]:
            meta.addWidget(Icon("folder", T["text2"], 15, 1.6))
            meta.addWidget(label(d["repo"], 13, color=T["text2"]))
            meta.addSpacing(8)
        if d["branch"]:
            meta.addWidget(Icon("branch", T["text2"], 15, 1.6))
            meta.addWidget(label(d["branch"], 13, color=T["text2"]))
        if not (d["repo"] or d["branch"]):
            meta.addWidget(label("No repository detected yet", 13, color=T["text2"]))
        meta.addStretch()
        col.addLayout(meta)
        tags = QHBoxLayout(); tags.setSpacing(6)
        deep = d["focus_score"] >= 60
        tags.addWidget(capsule("Deep focus" if deep else "Shallow focus",
                               SYS["green"] if deep else SYS["orange"]))
        if d["deep_minutes"]:
            tags.addWidget(capsule(f"{d['deep_minutes']} min streak", SYS["teal"]))
        tags.addStretch()
        col.addSpacing(4); col.addLayout(tags); col.addStretch()
        row.addLayout(col, 1)
        h.addLayout(row)
        self.lay.addWidget(hero)

        grid = QHBoxLayout(); grid.setSpacing(16)
        w, wl = card()
        wl.addLayout(caption("compass", "Where was I", SYS["blue"]))
        if d["where"]:
            wl.addWidget(label(d["where"], 15, QFont.Weight.DemiBold, wrap=True))
            wl.addWidget(label(f"Saved {d['where_ago']}  ·  {d['anchor']}", 12, color=T["text3"], wrap=True))
        else:
            wl.addWidget(label("Nothing saved yet. Your spot is captured automatically when an "
                               "interruption pulls you out of deep focus.", 13, color=T["text2"], wrap=True))
        wl.addStretch()
        n, nl = card()
        nl.addLayout(caption("pencil", "Next step", SYS["orange"]))
        nl.addWidget(label(d["next_step"] or "Press Journal on your keypad to leave yourself a note.",
                           15 if d["next_step"] else 13,
                           QFont.Weight.DemiBold if d["next_step"] else QFont.Weight.Normal,
                           None if d["next_step"] else T["text2"], wrap=True))
        nl.addStretch()
        grid.addWidget(w, 3); grid.addWidget(n, 2)
        self.lay.addLayout(grid)

        grid2 = QHBoxLayout(); grid2.setSpacing(16)
        rw = d.get("rewind") or {}
        r, rl = card()
        rl.addLayout(caption("rewind", "Since you left · cognitive rewind", SYS["teal"]))
        lines = []
        if rw.get("last_ide_file"):
            lines.append(("code", rw["last_ide_file"]))
        lines += [("pencil", f) for f in rw.get("changed_files", [])]
        lines += [("book", u.split("://", 1)[-1][:60]) for u in rw.get("browser_tabs", [])]
        if not lines:
            rl.addWidget(label("Your files, changes and relevant tabs from the last 30 minutes "
                               "will show up here.", 13, color=T["text2"], wrap=True))
        for ic, txt in lines[:6]:
            row_ = QHBoxLayout(); row_.setSpacing(8)
            row_.addWidget(Icon(ic, T["text3"], 14, 1.6))
            row_.addWidget(label(txt, 12.5, color=T["text2"])); row_.addStretch()
            rl.addLayout(row_)
        rl.addStretch()
        rd = d.get("radar") or {}
        b, bl = card()
        bl.addLayout(caption("radar", "Blocker radar", SYS["green"]))
        if rd:
            ci = rd.get("ci", "unknown")
            ci_col = {"pass": SYS["green"], "fail": SYS["red"], "pending": SYS["orange"]}.get(ci, SYS["gray"])
            for k, v, col in (("CI", {"pass": "Passing", "fail": "Failing", "pending": "Running"}.get(ci, "Unknown"), ci_col),
                              ("Reviews", f"{rd.get('prs', 0)} waiting", SYS["blue"] if rd.get("prs") else SYS["gray"]),
                              ("Behind main", f"{rd.get('behind', 0)} commits",
                               SYS["orange"] if rd.get("behind", 0) > 10 else SYS["gray"])):
                row_ = QHBoxLayout()
                row_.addWidget(label(k, 13, color=T["text2"])); row_.addStretch()
                row_.addWidget(capsule(v, col))
                bl.addLayout(row_)
        else:
            bl.addWidget(label("Add GITHUB_TOKEN and GITHUB_REPO to .env to see CI, reviews and "
                               "branch health here.", 13, color=T["text2"], wrap=True))
        bl.addStretch()
        grid2.addWidget(r, 3); grid2.addWidget(b, 2)
        self.lay.addLayout(grid2)

        c, cl = card(spacing=12)
        cl.addLayout(caption("chart", "Focus · last 10 minutes", SYS["indigo"]))
        cl.addWidget(AreaChart(d["timeline"] or [0, 0], color))
        self.lay.addWidget(c)

        pal = d.get("palette") or []
        if pal:
            q, ql = card(spacing=12)
            ql.addLayout(caption("terminal", "Quick commands · terminal palette", SYS["orange"]))
            row_ = QHBoxLayout(); row_.setSpacing(8)
            for i, slot in enumerate(pal[:6]):
                btn = QPushButton(slot.get("label", f"Slot {i}"))
                btn.setFont(font(12.5, QFont.Weight.DemiBold))
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setToolTip(slot.get("cmd", ""))
                btn.setStyleSheet(f"QPushButton {{ background: {T['sel']}; border-radius: 10px; padding: 8px 0; }}"
                                  f"QPushButton:hover {{ background: {T['hover']}; color: {SYS['blue']}; }}")
                btn.clicked.connect(lambda _, k=i: self.data.run_palette(k))
                row_.addWidget(btn, 1)
            ql.addLayout(row_)
            self.lay.addWidget(q)


class InboxPage(QWidget):
    def __init__(self, data: Data, flt: str = "ALL"):
        super().__init__()
        self.data, self.flt = data, flt or "ALL"
        self.items: list[dict] = []
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(14)
        bar = QHBoxLayout()
        seg = QFrame(); seg.setObjectName("segment")
        sl = QHBoxLayout(seg); sl.setContentsMargins(3, 3, 3, 3); sl.setSpacing(2)
        self.segs: dict[str, QPushButton] = {}
        for key in ("ALL", "HIGH", "MEDIUM", "LOW"):
            b = QPushButton(key.title()); b.setObjectName("seg"); b.setCheckable(True)
            b.setFont(font(12.5, QFont.Weight.DemiBold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, k=key: self.set_filter(k))
            self.segs[key] = b; sl.addWidget(b)
        bar.addWidget(seg); bar.addStretch()
        clr = QPushButton("Clear all"); clr.setObjectName("quiet")
        clr.setFont(font(13, QFont.Weight.Medium)); clr.setCursor(Qt.CursorShape.PointingHandCursor)
        clr.clicked.connect(self.clear_all); bar.addWidget(clr)
        root.addLayout(bar)
        inner = QWidget()
        self.list = QVBoxLayout(inner); self.list.setContentsMargins(0, 0, 6, 8); self.list.setSpacing(10)
        root.addWidget(scroll(inner), 1)
        self.refresh()

    def refresh(self):
        self.items = self.data.inbox(); self.render()

    def set_filter(self, k: str):
        self.flt = k; self.render()

    def render(self):
        for k, b in self.segs.items():
            n = len(self.items) if k == "ALL" else sum(1 for i in self.items if i.get("priority") == k)
            b.setText(f"{k.title()}  {n}" if n else k.title())
            b.setChecked(k == self.flt)
        clear(self.list)
        shown = [i for i in self.items if self.flt == "ALL" or i.get("priority") == self.flt]
        if not shown:
            self.list.addSpacing(80)
            ic = Icon("sparkle", SYS["blue"], 44, 1.4, tile=True)
            r = QHBoxLayout(); r.addStretch(); r.addWidget(ic); r.addStretch()
            self.list.addLayout(r)
            for txt, px, wt, col in (("You're all caught up", 20, QFont.Weight.DemiBold, None),
                                     ("Nothing is waiting for you. Stay in the zone.", 13,
                                      QFont.Weight.Normal, T["text2"])):
                l = label(txt, px, wt, col, display=px > 15)
                l.setAlignment(Qt.AlignmentFlag.AlignCenter); self.list.addWidget(l)
        for it in shown:
            self.list.addWidget(self.make_card(it))
        self.list.addStretch()

    def make_card(self, it: dict) -> QFrame:
        pr = it.get("priority", "MEDIUM")
        f, lay = card(16, 4)
        row = QHBoxLayout(); row.setSpacing(14); row.setAlignment(Qt.AlignmentFlag.AlignTop)
        icon, tint = SOURCE.get(it.get("source", ""), ("bubble", SYS["gray"]))
        row.addWidget(Icon(icon, tint, 38, 1.6, tile=True), 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout(); col.setSpacing(3)
        top = QHBoxLayout(); top.setSpacing(8)
        src = (it.get("source") or "manual").title()
        who = it.get("sender") and f"  ·  {it['sender']}" or ""
        top.addWidget(label(f"{src}{who}", 12, QFont.Weight.DemiBold, T["text2"]))
        top.addStretch()
        top.addWidget(label(_ago(it.get("arrived_at")), 12, color=T["text3"]))
        col.addLayout(top)
        col.addWidget(label(it.get("title") or "(no title)", 15, QFont.Weight.DemiBold, wrap=True))
        body = (it.get("body") or "").strip()
        if body:
            col.addWidget(label(body[:220] + ("…" if len(body) > 220 else ""), 13, color=T["text2"], wrap=True))
        bot = QHBoxLayout(); bot.setSpacing(6); bot.setContentsMargins(0, 6, 0, 0)
        bot.addWidget(capsule(pr.title(), PRIORITY.get(pr, SYS["gray"])))
        why = {"HOLD": ("Held for a break", SYS["teal"]), "BATCH": ("In digest", SYS["gray"]),
               "DELIVER": ("Delivered", SYS["green"])}.get(it.get("decision", ""))
        if why:
            bot.addWidget(capsule(*why))
        bot.addStretch()
        if it.get("url"):
            o = QPushButton("Open"); o.setObjectName("pill"); o.setFont(font(12.5, QFont.Weight.DemiBold))
            o.setStyleSheet(f"QPushButton {{ background: {SYS['blue']}; color: white; border-radius: 13px;"
                            "padding: 5px 16px; } QPushButton:hover { background: #409cff; }")
            o.setCursor(Qt.CursorShape.PointingHandCursor)
            o.clicked.connect(lambda _, u=it["url"]: webbrowser.open(u)); bot.addWidget(o)
        d = QPushButton("Done"); d.setObjectName("link"); d.setFont(font(13, QFont.Weight.DemiBold))
        d.setCursor(Qt.CursorShape.PointingHandCursor)
        d.clicked.connect(lambda _, i=it["id"]: self.dismiss(i)); bot.addWidget(d)
        col.addLayout(bot)
        row.addLayout(col, 1)
        lay.addLayout(row)
        return f

    def dismiss(self, nid: str):
        self.data.dismiss(nid)
        self.items = [i for i in self.items if i["id"] != nid]; self.render()

    def clear_all(self):
        keep = []
        for i in self.items:
            if self.flt == "ALL" or i.get("priority") == self.flt:
                self.data.dismiss(i["id"])
            else:
                keep.append(i)
        self.items = keep; self.render()


class InsightsPage(Page):
    def build(self):
        d = self.data.insights()
        tiles = QHBoxLayout(); tiles.setSpacing(16)
        m = d["deep_minutes"]
        for icon, title, value, color in [
            ("target", "Deep work · 7 days", f"{m // 60}h {m % 60}m", SYS["blue"]),
            ("lock", "Interruptions held", str(d["held"]), SYS["teal"]),
            ("bubble", "Let through", str(d["delivered"]), SYS["green"]),
        ]:
            f, l = card(18, 10)
            l.addLayout(caption(icon, title, color))
            l.addWidget(label(value, 32, QFont.Weight.DemiBold, color, display=True))
            tiles.addWidget(f)
        self.lay.addLayout(tiles)

        f, l = card(spacing=12)
        l.addLayout(caption("clock", "When you focus best", SYS["indigo"]))
        best = d.get("best_hours") or []
        if best:
            nice = [f"{(int(b[:2]) % 12) or 12} {'AM' if int(b[:2]) < 12 else 'PM'}" for b in best]
            l.addWidget(label(", ".join(nice), 20, QFont.Weight.DemiBold, display=True))
        else:
            l.addWidget(label("Collecting data. Check back after a day of work.", 13, color=T["text2"]))
        hours = d.get("hours") or {}
        if hours:
            l.addWidget(HourBars(hours, {int(b[:2]) for b in best}))
        self.lay.addWidget(f)

        f, l = card(spacing=12)
        l.addLayout(caption("tray", "Who interrupts you", SYS["purple"]))
        ints = d.get("interruptions") or {}
        if not ints:
            l.addWidget(label("No interruptions recorded yet.", 13, color=T["text2"]))
        top = max(ints.values()) if ints else 1
        for src, n in ints.items():
            icon, tint = SOURCE.get(src, ("bubble", SYS["gray"]))
            r = QHBoxLayout(); r.setSpacing(12)
            r.addWidget(Icon(icon, tint, 28, 1.6, tile=True))
            r.addWidget(label(src.title(), 14, QFont.Weight.Medium))
            r.addStretch()
            bar = Meter(n / top, tint); r.addWidget(bar)
            r.addWidget(label(str(n), 14, QFont.Weight.DemiBold, T["text2"]))
            l.addLayout(r)
        self.lay.addWidget(f)
        foot = QHBoxLayout(); foot.setSpacing(6)
        foot.addWidget(Icon("lock", T["text3"], 13, 1.6))
        foot.addWidget(label("Computed and stored on this PC only. Nothing leaves your machine.", 12, color=T["text3"]))
        foot.addStretch()
        self.lay.addLayout(foot)


class Meter(QWidget):
    def __init__(self, frac: float, color: str):
        super().__init__()
        self.frac, self.color = max(0.04, min(1, frac)), QColor(color)
        self.setFixedSize(220, 8)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(T["track"])
        p.drawRoundedRect(QRectF(0, 0, self.width(), 8), 4, 4)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 0, self.width() * self.frac, 8), 4, 4)


# ── Window ────────────────────────────────────────────────────────────────────
class Hub(QWidget):
    TABS = [("focus", "Focus", "target"), ("inbox", "Inbox", "tray"), ("insights", "Insights", "chart")]
    SHADOW = 18

    def __init__(self, tab: str = "focus", flt: str = "", demo: bool = False):
        super().__init__()
        self.setWindowTitle("Deep Work AI")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(940 + 2 * self.SHADOW, 640 + 2 * self.SHADOW)
        self._drag: QPoint | None = None
        data = Data(demo)

        outer = QVBoxLayout(self)
        s = self.SHADOW
        outer.setContentsMargins(s, s - 4, s, s + 4)
        root = QFrame(); root.setObjectName("root")   # no QGraphicsEffect: it rasterises → blurry text
        outer.addWidget(root)
        body = QHBoxLayout(root); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)

        side = QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(216)
        sl = QVBoxLayout(side); sl.setContentsMargins(14, 22, 14, 18); sl.setSpacing(2)
        brand = QHBoxLayout(); brand.setSpacing(10); brand.setContentsMargins(6, 0, 0, 0)
        brand.addWidget(Icon("sparkle", SYS["blue"], 30, 1.5, tile=True))
        bt = QVBoxLayout(); bt.setSpacing(0)
        bt.addWidget(label("Deep Work", 15, QFont.Weight.Bold, display=True))
        bt.addWidget(label("Focus OS", 11.5, color=T["text3"]))
        brand.addLayout(bt); brand.addStretch()
        sl.addLayout(brand); sl.addSpacing(24)

        self.stack = QStackedWidget()
        self.pages = {"focus": FocusPage(data), "inbox": InboxPage(data, flt), "insights": InsightsPage(data)}
        self.navs: dict[str, QPushButton] = {}
        self.nav_icons: dict[str, Icon] = {}
        for key, text, icon in self.TABS:
            b = QPushButton(text); b.setObjectName("nav"); b.setCheckable(True)
            b.setFont(font(13.5, QFont.Weight.Medium)); b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(38)
            b.clicked.connect(lambda _, k=key: self.show_tab(k))
            ic = Icon(icon, T["text2"], 18, 1.7); ic.setParent(b); ic.move(13, 10)
            self.nav_icons[key] = ic
            sl.addWidget(b); self.navs[key] = b; self.stack.addWidget(self.pages[key])
        sl.addStretch()
        lk = QHBoxLayout(); lk.setSpacing(6); lk.setContentsMargins(8, 0, 0, 0)
        lk.addWidget(Icon("lock", SYS["green"], 13, 1.7))
        lk.addWidget(label("On-device · Offline", 11.5, QFont.Weight.Medium, T["text3"])); lk.addStretch()
        sl.addLayout(lk)
        body.addWidget(side)

        main = QVBoxLayout(); main.setContentsMargins(30, 22, 22, 18); main.setSpacing(18)
        head = QHBoxLayout()
        tl = QVBoxLayout(); tl.setSpacing(2)
        self.title = label("", 28, QFont.Weight.Bold, display=True)
        self.clock = label("", 13, color=T["text2"])
        tl.addWidget(self.clock); tl.addWidget(self.title)
        head.addLayout(tl); head.addStretch()
        x = QPushButton(); x.setFixedSize(28, 28); x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(f"QPushButton {{ background: {T['sel']}; border-radius: 14px; }}"
                        f"QPushButton:hover {{ background: {SYS['red']}; }}")
        xi = Icon("close", T["text2"], 16, 1.8); xi.setParent(x); xi.move(6, 6)
        x.clicked.connect(self.close)
        head.addWidget(x, 0, Qt.AlignmentFlag.AlignTop)
        main.addLayout(head)
        main.addWidget(self.stack, 1)
        body.addLayout(main, 1)

        self.setStyleSheet(qss())
        self.show_tab(tab if tab in self.pages else "focus")
        self._set_clock()
        t = QTimer(self); t.timeout.connect(self._tick); t.start(15_000)

    def paintEvent(self, _):
        # Soft, crisp window shadow painted directly (no rasterising effect).
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.SHADOW
        r = QRectF(self.rect()).adjusted(s, s - 4, -s, -s - 4)
        for i in range(s, 0, -1):
            a = int(55 * (1 - i / s) ** 2)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, a // 3))
            p.drawRoundedRect(r.adjusted(-i, -i + 6, i, i + 6), 20 + i, 20 + i)

    def show_tab(self, key: str):
        for k, b in self.navs.items():
            b.setChecked(k == key)
            self.nav_icons[k].color = QColor(SYS["blue"] if k == key else T["text2"])
            self.nav_icons[k].update()
        self.stack.setCurrentWidget(self.pages[key])
        self.title.setText(dict((k, t) for k, t, _ in self.TABS)[key])

    def _set_clock(self):
        self.clock.setText(datetime.now().strftime("%A, %d %B").upper())
        self.clock.setFont(font(12, QFont.Weight.DemiBold))

    def _tick(self):
        self._set_clock()
        page = self.stack.currentWidget()
        if isinstance(page, Page):
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


def _apply_theme(mode: str, app: QApplication):
    dark = True
    if mode == "light":
        dark = False
    elif mode == "auto":
        try:
            dark = app.styleHints().colorScheme() != Qt.ColorScheme.Light
        except AttributeError:
            dark = True
    T.clear(); T.update(DARK if dark else LIGHT)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deep Work AI Hub")
    ap.add_argument("--tab", default="focus", choices=["focus", "inbox", "insights"])
    ap.add_argument("--filter", default="", help="HIGH|MEDIUM|LOW (inbox)")
    ap.add_argument("--theme", default="auto", choices=["auto", "light", "dark"])
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--screenshot", default="", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    # Crisp at 125 % / 150 % Windows scaling (default rounding makes text soft).
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    _apply_theme(a.theme, app)
    w = Hub(a.tab, a.filter.upper(), a.demo)
    if a.screenshot:
        w.show(); app.processEvents()
        w.grab().save(a.screenshot)
        return 0
    scr = app.primaryScreen().availableGeometry()
    w.move(scr.center() - w.rect().center())
    w.show(); w.activateWindow()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
