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
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from deepworkai.service.paths import DATA_DIR as DATA  # noqa: E402

from PyQt6.QtCore import Qt, QTimer, QRectF, QPoint, QPointF
from PyQt6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QGuiApplication, QImage,
                         QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                             QSizePolicy,
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
# Monochrome bento palette (neutral, shadcn-style). Colour is reserved for the
# one thing that must stand out: a HIGH-priority interruption.
DARK = {
    "window": "#0a0a0a", "sidebar": "#0a0a0a", "card": "#171717", "card2": "#171717",
    "muted": "#262626", "hover": "#1f1f1f", "line": "#262626", "line_q": QColor(255, 255, 255, 16),
    "text": "#fafafa", "text2": "#a3a3a3", "text3": "#737373", "track": QColor(255, 255, 255, 26),
    "sel": "#1f1f1f", "seg": "#171717", "seg_on": "#262626",
    "primary": "#e5e5e5", "on_primary": "#171717", "on_primary2": "#525252",
}
LIGHT = {
    "window": "#ffffff", "sidebar": "#ffffff", "card": "#ffffff", "card2": "#ffffff",
    "muted": "#f5f5f5", "hover": "#f5f5f5", "line": "#e5e5e5", "line_q": QColor(0, 0, 0, 14),
    "text": "#0a0a0a", "text2": "#525252", "text3": "#a3a3a3", "track": QColor(0, 0, 0, 20),
    "sel": "#f5f5f5", "seg": "#f5f5f5", "seg_on": "#ffffff",
    "primary": "#171717", "on_primary": "#fafafa", "on_primary2": "#a3a3a3",
}
SYS: dict = {}
T = dict(DARK)


def _apply_accents():
    """Every former accent becomes a shade of grey; red stays for urgent items only."""
    SYS.clear()
    SYS.update({k: T["text"] for k in ("blue", "green", "teal", "indigo", "purple", "orange")})
    SYS.update(gray=T["text3"], red="#f87171" if T is not None and T["window"] == DARK["window"] else "#dc2626")


_apply_accents()
PRIORITY: dict = {}
SOURCE = {"slack": ("bubble", "gray"), "github": ("merge", "gray"), "jira": ("ticket", "gray"),
          "teams": ("bubble", "gray"), "manual": ("pencil", "gray")}
ACTIVITY = {
    "coding":        ("Coding",        "code",    "text"),
    "debugging":     ("Debugging",     "bug",     "text"),
    "reviewing":     ("Reviewing",     "merge",   "text"),
    "researching":   ("Researching",   "book",    "text"),
    "communicating": ("Communicating", "bubble",  "text"),
    "meeting":       ("In a meeting",  "clock",   "text"),
    "idle":          ("Idle",          "moon",    "text"),
}


def _resolve_palette():
    """Colour names in SOURCE/ACTIVITY → current theme colours."""
    PRIORITY.clear()
    PRIORITY.update({"HIGH": SYS["red"], "MEDIUM": T["text2"], "LOW": T["text3"]})
    for k, (ic, c) in list(SOURCE.items()):
        SOURCE[k] = (ic, T["text2"])
    for k, (n, ic, c) in list(ACTIVITY.items()):
        ACTIVITY[k] = (n, ic, T["text"])


_resolve_palette()
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
    #root {{ background: {T['window']}; border-radius: 24px; border: 1px solid {T['line']}; }}
    #sidebar {{ background: {T['sidebar']}; border-top-left-radius: 24px;
                border-bottom-left-radius: 24px; border-right: 1px solid {T['line']}; }}
    #card {{ background: {T['card']}; border: 1px solid {T['line']}; border-radius: 24px; }}
    #mutedcard {{ background: {T['muted']}; border: 1px solid {T['line']}; border-radius: 24px; }}
    QPushButton {{ border: none; }}
    QPushButton#nav {{ text-align: left; padding: 9px 12px 9px 40px; border-radius: 12px;
                       color: {T['text2']}; }}
    QPushButton#nav:hover {{ background: {T['sel']}; color: {T['text']}; }}
    QPushButton#nav:checked {{ background: {T['muted']}; color: {T['text']}; }}
    #segment {{ background: {T['card']}; border: 1px solid {T['line']}; border-radius: 12px; }}
    QPushButton#seg {{ padding: 6px 14px; border-radius: 9px; color: {T['text3']}; }}
    QPushButton#seg:checked {{ background: {T['muted']}; color: {T['text']}; }}
    QPushButton#link {{ color: {T['text']}; padding: 4px 6px; }}
    QPushButton#link:hover {{ color: {T['text2']}; }}
    QPushButton#quiet {{ color: {T['text3']}; padding: 4px 6px; }}
    QPushButton#quiet:hover {{ color: {T['text']}; }}
    QPushButton#pill {{ background: {T['text']}; color: {T['window']}; padding: 6px 14px; border-radius: 14px; }}
    QPushButton#chipbtn {{ background: {T['muted']}; color: {T['text2']}; border: 1px solid {T['line']};
                           border-radius: 12px; padding: 9px 0; }}
    QPushButton#chipbtn:hover {{ color: {T['text']}; border-color: {T['text3']}; }}
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
    l.setTextFormat(Qt.TextFormat.PlainText)       # never render notification text as HTML
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


class Pill(QLabel):
    """Rounded pill drawn by hand (Qt ignores border-radius on some label styles)."""
    def __init__(self, text: str, fg: str, bg: QColor):
        super().__init__(text)
        self._bg = bg
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setStyleSheet(f"color: {fg}; background: transparent; padding: 5px 12px;")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(self._bg)
        r = QRectF(self.rect()); p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.end()
        super().paintEvent(e)


def capsule(text: str, color: str | None = None, on_primary: bool = False) -> QLabel:
    """Small uppercase pill (like 'MARKET SHARE'). Monochrome unless urgent (red)."""
    if on_primary:
        fg = T["on_primary2"]
        bg = QColor(T["on_primary"]); bg.setAlpha(22)
    elif color and color == SYS.get("red"):
        fg = color; bg = QColor(color); bg.setAlpha(30)
    else:
        fg = T["text2"]; bg = QColor(T["muted"])
    l = Pill(text.upper(), fg, bg)
    f = font(10.5, QFont.Weight.DemiBold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
    l.setFont(f)
    return l


def overline(text: str, color: str | None = None) -> QLabel:
    """Tracked uppercase label ('GROWTH')."""
    l = QLabel(text.upper()); l.setTextFormat(Qt.TextFormat.PlainText)
    f = font(11, QFont.Weight.DemiBold); f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
    l.setFont(f); l.setStyleSheet(f"color: {color or T['text3']};")
    return l


def big(text: str, px: int, color: str | None = None) -> QLabel:
    """Oversized, thin, tightly tracked number — the hero of each card."""
    l = QLabel(text); l.setTextFormat(Qt.TextFormat.PlainText)
    f = font(px, QFont.Weight.Light, display=True)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 94 if px >= 48 else 98)
    l.setFont(f); l.setStyleSheet(f"color: {color or T['text']};")
    return l


def muted_card(pad: int = 26, spacing: int = 8) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame(); f.setObjectName("mutedcard")
    lay = QVBoxLayout(f); lay.setContentsMargins(pad, pad, pad, pad); lay.setSpacing(spacing)
    return f, lay


class HatchCard(QFrame):
    """The light hero card: soft fill + 45° hatching that fades out from the top-right."""
    def __init__(self, pad: int = 34, spacing: int = 8):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(pad, pad, pad, pad); self.lay.setSpacing(spacing)
        self._cache: tuple | None = None

    def _hatch(self, w: int, h: int, dpr: float) -> QImage:
        img = QImage(int(w * dpr), int(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr); img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(128, 128, 128, 90); p.setPen(QPen(c, 1))
        for x in range(-h, w + h, 10):
            p.drawLine(QPointF(x, 0), QPointF(x + h, h))
        # fade: ellipse anchored at the top-right corner (80% × 50%)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        p.translate(w, 0); p.scale(w * 0.8, h * 0.5)
        g = QRadialGradient(QPointF(0, 0), 1.0)
        g.setColorAt(0.0, QColor(0, 0, 0, 255)); g.setColorAt(0.64, QColor(0, 0, 0, 255))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(QRectF(-2.0, -1.0, 3.0, 4.0), QBrush(g))   # whole card: outside the ellipse → transparent
        p.end()
        return img

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath(); path.addRoundedRect(r, 24, 24)
        p.fillPath(path, QColor(T["primary"]))
        key = (self.width(), self.height(), self.devicePixelRatioF())
        if not self._cache or self._cache[0] != key:          # rebuilt only on resize
            self._cache = (key, self._hatch(self.width(), self.height(), self.devicePixelRatioF()))
        p.setClipPath(path); p.setOpacity(0.3 if T["primary"] == DARK["primary"] else 0.45)
        p.drawImage(0, 0, self._cache[1])


class Bars(QWidget):
    """Slim rounded bars (the 'Growth' sparkline). Values 0-100."""
    def __init__(self, values: list[float], height: int = 34, bar: float = 6, gap: float = 4,
                 color: str | None = None, dim_until: int = 0):
        super().__init__()
        self.values = [max(0.0, min(100.0, float(v))) for v in values] or [0.0]
        self.color = QColor(color or T["text"]); self.bar, self.gap = bar, gap
        self.dim_until = dim_until
        self.setFixedHeight(height)
        self.setFixedWidth(int(len(self.values) * (bar + gap) - gap))

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i, v in enumerate(self.values):
            h = max(self.bar, v / 100 * self.height())
            c = QColor(self.color)
            if i < self.dim_until:
                c.setAlpha(90)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(i * (self.bar + self.gap), self.height() - h, self.bar, h),
                              self.bar / 2, self.bar / 2)


class Badge(QWidget):
    """Round icon badge (the ★ circle)."""
    def __init__(self, icon: str, size: int = 44):
        super().__init__()
        self.icon = icon; self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width()
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(T["window"]))
        p.drawEllipse(QRectF(0, 0, s, s))
        p.translate(s * 0.27, s * 0.27); p.scale(s * 0.46 / 20, s * 0.46 / 20)
        pen = QPen(QColor(T["text"]), 1.7); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(_icon_path(self.icon))


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


def open_url(url: str):
    """Only real web links. A notification could carry file:// or a local .exe path,
    which webbrowser.open would hand to the OS to execute."""
    from urllib.parse import urlparse
    u = urlparse(url or "")
    if u.scheme in ("http", "https") and u.netloc:
        webbrowser.open(url)


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


def _bento() -> QGridLayout:
    g = QGridLayout(); g.setSpacing(16); g.setContentsMargins(0, 0, 0, 0)
    for c in range(6):
        g.setColumnStretch(c, 1); g.setColumnMinimumWidth(c, 40)
    return g


def _held_count(data) -> int:
    return sum(1 for i in data.inbox() if i.get("decision") in ("HOLD", "BATCH"))


class FocusPage(Page):
    def build(self):
        d = self.data.focus()
        name = ACTIVITY.get(d["activity"], ACTIVITY["idle"])[0]
        g = _bento()

        # Hero — focus score
        hero = HatchCard()
        hero.lay.addWidget(capsule("Focus score", on_primary=True))
        hero.lay.addSpacing(10)
        hero.lay.addWidget(big(str(d["focus_score"]), 88, T["on_primary"]))
        hero.lay.addStretch()
        where = " · ".join(x for x in (d["repo"], d["branch"]) if x)
        desc = f"{name}" + (f" in {where}" if where else "") + \
               (f". {d['deep_minutes']} minute streak." if d["deep_minutes"] else ".")
        hero.lay.addWidget(label(desc, 14, color=T["on_primary2"], wrap=True))
        hero.setMinimumHeight(300)
        g.addWidget(hero, 0, 0, 2, 3)

        # Trend — sparkline
        tr, tl = muted_card(28)
        row = QHBoxLayout()
        col = QVBoxLayout(); col.setSpacing(4)
        col.addWidget(overline("Last 10 minutes"))
        col.addWidget(big("Deep focus" if d["focus_score"] >= 60 else "Shallow", 30))
        row.addLayout(col); row.addStretch()
        row.addWidget(Bars(d["timeline"][-11:] or [0], height=40), 0, Qt.AlignmentFlag.AlignBottom)
        tl.addLayout(row)
        g.addWidget(tr, 0, 3, 1, 3)

        # Held interruptions
        hc, hl = card(20, 2)
        n = big(str(_held_count(self.data)), 30); n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        k = overline("Held"); k.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addStretch(); hl.addWidget(n); hl.addWidget(k); hl.addStretch()
        g.addWidget(hc, 1, 3, 1, 1)

        # Where was I
        wc, wl = muted_card(24)
        row = QHBoxLayout(); row.setSpacing(16)
        row.addWidget(Badge("compass"), 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout(); col.setSpacing(3)
        where_txt = (d["where"] or "").split(" (")[0]
        act, _, place = where_txt.partition(" in ")
        head = (act or "Nothing saved yet").split(" on ")[0]
        col.addWidget(label(head[:1].upper() + head[1:], 16, QFont.Weight.Medium))
        sub = f"{place.replace('@', ' · ')} · {d['where_ago']}" if place else (
              f"Saved {d['where_ago']}" if d["where"] else "Saved when you're interrupted")
        sl0 = label(sub, 12, QFont.Weight.DemiBold, T["text3"], wrap=True)
        sl0.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        col.addWidget(sl0)
        row.addLayout(col, 1)
        wl.addLayout(row)
        g.addWidget(wc, 1, 4, 1, 2)
        self.lay.addLayout(g)

        # Second band: note + since you left
        g2 = _bento()
        nc, nl = card(26, 10)
        nl.addWidget(overline("Next step"))
        self.note = NoteEdit(d["next_step"], self._save_note)
        self.note.setPlaceholderText("What's your next step?  Enter to save")
        self.note.setFont(font(17, QFont.Weight.Normal, display=True))
        self.note.setFixedHeight(76)
        self.note.setStyleSheet(
            f"QPlainTextEdit {{ background: transparent; border: none; padding: 0; color: {T['text']}; }}")
        self.note_hint = label("", 11.5, color=T["text3"])
        nl.addWidget(self.note); nl.addWidget(self.note_hint)
        g2.addWidget(nc, 0, 0, 1, 3)

        rw = d.get("rewind") or {}
        sc, sl_ = card(26, 8)
        sl_.addWidget(overline("Since you left"))
        lines = ([rw["last_ide_file"]] if rw.get("last_ide_file") else []) + list(rw.get("changed_files", []))
        lines = list(dict.fromkeys(lines))[:3] + [u.split("://", 1)[-1][:56] for u in rw.get("browser_tabs", [])][:2]
        if not lines:
            sl_.addWidget(label("Files and tabs from the last 30 minutes appear here.", 13, color=T["text3"], wrap=True))
        for txt in lines:
            sl_.addWidget(label(txt, 13.5, color=T["text2"]))
        sl_.addStretch()
        g2.addWidget(sc, 0, 3, 1, 3)
        self.lay.addLayout(g2)

        # Third band: radar (only when configured) + quick commands
        rd = d.get("radar") or {}
        pal = d.get("palette") or []
        if rd or pal:
            g3 = _bento()
            col0 = 0
            if rd:
                ci = {"pass": "Passing", "fail": "Failing", "pending": "Running"}.get(rd.get("ci"), "Unknown")
                rc, rl = card(24, 2)
                rl.addWidget(overline("CI"))
                rl.addWidget(big(ci, 24, SYS["red"] if rd.get("ci") == "fail" else T["text"]))
                prs, behind = rd.get("prs", 0), rd.get("behind", 0)
                rl.addWidget(label(f"{prs} review{'s' if prs != 1 else ''} · {behind} behind main", 12.5,
                                   color=T["text3"]))
                g3.addWidget(rc, 0, 0, 1, 2); col0 = 2
            if pal:
                qc, ql = card(24, 12)
                ql.addWidget(overline("Quick commands"))
                row = QHBoxLayout(); row.setSpacing(8)
                for i, slot in enumerate(pal[:6]):
                    btn = QPushButton(slot.get("label", f"Slot {i}")); btn.setObjectName("chipbtn")
                    btn.setFont(font(12.5, QFont.Weight.Medium))
                    btn.setCursor(Qt.CursorShape.PointingHandCursor); btn.setToolTip(slot.get("cmd", ""))
                    btn.clicked.connect(lambda _, k=i: self.data.run_palette(k))
                    row.addWidget(btn, 1)
                ql.addLayout(row)
                g3.addWidget(qc, 0, col0, 1, 6 - col0)
            self.lay.addLayout(g3)


class NoteEdit(QPlainTextEdit):
    """Wraps long notes. Enter saves, Shift+Enter is a new line, max 300 chars."""
    def __init__(self, text: str, on_save):
        super().__init__(text)
        self.on_save = on_save
        self.document().setModified(False)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.on_save(); return
        super().keyPressEvent(e)
        if len(self.toPlainText()) > 300:
            self.setPlainText(self.toPlainText()[:300])
            self.moveCursor(self.textCursor().MoveOperation.End)

    def isModified(self) -> bool:
        return self.document().isModified()

    def selectAll(self):
        super().selectAll()


def _focus_save_note(self):
    text = self.note.toPlainText().strip()
    if not self.data.demo:
        try:
            (DATA / "next_step.txt").write_text(text, encoding="utf-8")
        except OSError as e:
            self.note_hint.setText(f"Couldn't save: {e}"); return
    self.note_hint.setText("Saved ✓" if text else "Cleared")
    self.note.document().setModified(False)
    self.note.clearFocus()


def _focus_busy(self) -> bool:
    n = getattr(self, "note", None)
    try:
        return bool(n and (n.hasFocus() or n.isModified()))
    except RuntimeError:                      # widget already deleted by a rebuild
        return False


FocusPage._save_note = _focus_save_note
FocusPage.busy = _focus_busy


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
            ic = Badge("sparkle", 52)
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
        f, lay = card(22, 6)
        top = QHBoxLayout(); top.setSpacing(8)
        top.addWidget(Dot(PRIORITY.get(pr, T["text3"])), 0, Qt.AlignmentFlag.AlignVCenter)
        src = (it.get("source") or "manual").title()
        who = f"  ·  {it['sender']}" if it.get("sender") else ""
        top.addWidget(overline(f"{pr.title()}  ·  {src}{who}", SYS["red"] if pr == "HIGH" else None))
        top.addStretch()
        top.addWidget(label(_ago(it.get("arrived_at")), 12, color=T["text3"]))
        lay.addLayout(top)
        lay.addSpacing(2)
        lay.addWidget(label(it.get("title") or "(no title)", 16, QFont.Weight.Medium, wrap=True))
        body = (it.get("body") or "").strip()
        if body:
            lay.addWidget(label(body[:220] + ("…" if len(body) > 220 else ""), 13.5, color=T["text2"], wrap=True))
        bot = QHBoxLayout(); bot.setSpacing(6); bot.setContentsMargins(0, 8, 0, 0)
        why = {"HOLD": "Held until your next break", "BATCH": "Saved for your digest",
               "DELIVER": "Let through"}.get(it.get("decision", ""), "")
        bot.addWidget(label(why, 12.5, color=T["text3"]))
        bot.addStretch()
        if it.get("url"):
            o = QPushButton("Open"); o.setObjectName("pill"); o.setFont(font(12.5, QFont.Weight.DemiBold))
            o.setCursor(Qt.CursorShape.PointingHandCursor)
            o.clicked.connect(lambda _, u=it["url"]: open_url(u)); bot.addWidget(o)
        d = QPushButton("Done"); d.setObjectName("quiet"); d.setFont(font(13, QFont.Weight.DemiBold))
        d.setCursor(Qt.CursorShape.PointingHandCursor)
        d.clicked.connect(lambda _, i=it["id"]: self.dismiss(i)); bot.addWidget(d)
        lay.addLayout(bot)
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
        g = _bento()
        m = d["deep_minutes"]
        best = d.get("best_hours") or []
        nice = [f"{(int(b[:2]) % 12) or 12} {'AM' if int(b[:2]) < 12 else 'PM'}" for b in best]

        hero = HatchCard()
        hero.lay.addWidget(capsule("Deep work · 7 days", on_primary=True))
        hero.lay.addSpacing(10)
        hero.lay.addWidget(big(f"{m // 60}h {m % 60:02d}m", 64, T["on_primary"]))
        hero.lay.addStretch()
        hero.lay.addWidget(label(("You focus best around " + ", ".join(nice) + ".") if nice
                                 else "Keep working — your focus pattern appears after a day.",
                                 14, color=T["on_primary2"], wrap=True))
        hero.setMinimumHeight(300)
        g.addWidget(hero, 0, 0, 2, 3)

        hc, hl = muted_card(28)
        row = QHBoxLayout()
        col = QVBoxLayout(); col.setSpacing(4)
        col.addWidget(overline("Interruptions held"))
        col.addWidget(big(str(d["held"]), 34))
        row.addLayout(col); row.addStretch()
        hours = list((d.get("hours") or {}).values())[-11:]
        if hours:
            row.addWidget(Bars(hours, height=40), 0, Qt.AlignmentFlag.AlignBottom)
        hl.addLayout(row)
        g.addWidget(hc, 0, 3, 1, 3)

        lc, ll = card(20, 2)
        n = big(str(d["delivered"]), 30); n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        k = overline("Let through"); k.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addStretch(); ll.addWidget(n); ll.addWidget(k); ll.addStretch()
        g.addWidget(lc, 1, 3, 1, 1)

        ints = d.get("interruptions") or {}
        tc, tl = muted_card(24)
        row = QHBoxLayout(); row.setSpacing(16)
        row.addWidget(Badge("tray"), 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout(); col.setSpacing(3)
        if ints:
            src, cnt = next(iter(ints.items()))
            col.addWidget(label(f"{src.title()} · {cnt} of {sum(ints.values())}", 14, QFont.Weight.Medium))
            col.addWidget(label("Top source", 12, QFont.Weight.DemiBold, T["text3"]))
        else:
            col.addWidget(label("No interruptions yet", 14, QFont.Weight.Medium))
            col.addWidget(label("Sources appear as they arrive", 12, QFont.Weight.DemiBold, T["text3"]))
        row.addLayout(col, 1)
        tl.addLayout(row)
        g.addWidget(tc, 1, 4, 1, 2)
        self.lay.addLayout(g)

        if len(ints) > 1:
            f, l = card(26, 12)
            l.addWidget(overline("Who interrupts you"))
            top = max(ints.values())
            for src, cnt in ints.items():
                r = QHBoxLayout(); r.setSpacing(12)
                r.addWidget(label(src.title(), 14, color=T["text2"]))
                r.addStretch()
                r.addWidget(Meter(cnt / top, T["text"]))
                r.addWidget(label(str(cnt), 14, color=T["text3"]))
                l.addLayout(r)
            self.lay.addWidget(f)
        foot = label("Computed and stored on this PC only. Nothing leaves your machine.", 12, color=T["text3"])
        self.lay.addWidget(foot)


class Dot(QWidget):
    def __init__(self, color: str, size: int = 7):
        super().__init__()
        self.color = QColor(color); self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.color); p.drawEllipse(QRectF(self.rect()))


class Meter(QWidget):
    def __init__(self, frac: float, color: str):
        super().__init__()
        self.frac, self.color = max(0.04, min(1, frac)), QColor(color)
        self.setFixedSize(160, 6)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(T["track"])
        p.drawRoundedRect(QRectF(0, 0, self.width(), 6), 3, 3)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 0, self.width() * self.frac, 6), 3, 3)


# ── Window ────────────────────────────────────────────────────────────────────
# Hidden this long → exit to give memory back (DEEPWORKAI_UI_KEEPALIVE_MIN, 0 = never).
import os as _os
KEEPALIVE_S = float(_os.environ.get("DEEPWORKAI_UI_KEEPALIVE_MIN", "20")) * 60 or float("inf")


class Hub(QWidget):
    TABS = [("focus", "Focus", "target"), ("timeline", "Time Travel", "rewind"),
            ("inbox", "Inbox", "tray"), ("insights", "Insights", "chart")]
    SHADOW = 18

    def __init__(self, tab: str = "focus", flt: str = "", demo: bool = False,
                 persistent: bool = False, demo_index: int | None = None):
        super().__init__()
        self.persistent = persistent
        self._hidden_since = time.time()
        self._by_dial = False
        self._cmd_mtime = 0.0
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
        brand.addWidget(Badge("sparkle", 32))
        bt = QVBoxLayout(); bt.setSpacing(0)
        bt.addWidget(label("Deep Work", 15, QFont.Weight.Bold, display=True))
        bt.addWidget(label("Focus OS", 11.5, color=T["text3"]))
        brand.addLayout(bt); brand.addStretch()
        sl.addLayout(brand); sl.addSpacing(24)

        self.stack = QStackedWidget()
        from deepworkai.ui.timetravel import TimelinePage
        self.pages = {"focus": FocusPage(data),
                      "timeline": TimelinePage(demo, demo_index, on_finish=self._travel_done),
                      "inbox": InboxPage(data, flt), "insights": InsightsPage(data)}
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
        lk.addWidget(Icon("lock", T["text3"], 13, 1.7))
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
        x.setStyleSheet(f"QPushButton {{ background: {T['muted']}; border-radius: 14px; }}"
                        f"QPushButton:hover {{ background: {T['line']}; }}")
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
        # Fast, cheap loop: one stat() per file — commands from the service + dial state.
        self.fast = QTimer(self); self.fast.timeout.connect(self._fast); self.fast.start(40)
        if persistent:
            self._read_cmd(initial=True)

    # ── service → UI commands (data/ui_cmd.json) ──────────────────────────────
    def _read_cmd(self, initial: bool = False):
        f = DATA / "ui_cmd.json"
        try:
            m = f.stat().st_mtime
        except OSError:
            return
        if m == self._cmd_mtime:
            return
        self._cmd_mtime = m
        try:
            cmd = json.loads(f.read_text())
        except (OSError, ValueError):
            return
        if initial and time.time() - cmd.get("ts", 0) > 5:
            return                                    # stale command from an earlier run
        if cmd.get("action") == "hide":
            self.hide(); return
        if cmd.get("action") == "show":
            self.present(cmd.get("tab", "focus"), cmd.get("focus_note", False),
                         cmd.get("by_dial", False))

    def present(self, tab: str, focus_note: bool = False, by_dial: bool = False):
        self._by_dial = by_dial and (self.isHidden() or self._by_dial)
        key = tab if tab in self.pages else "focus"
        if self.isHidden() and self.stack.currentWidget() is self.pages[key]:
            self.pages[key].refresh()         # was hidden: show fresh data, not stale
        self.show_tab(key)
        if not self.isVisible():
            scr = QApplication.primaryScreen().availableGeometry()
            self.move(scr.center() - self.rect().center())
        self.show(); self.raise_(); self.activateWindow()
        if focus_note and tab == "focus":
            n = getattr(self.pages["focus"], "note", None)
            if n is not None:
                n.setFocus(); n.selectAll()

    def _fast(self):
        self._read_cmd()
        if self.persistent and self.isHidden() and not self.pages["timeline"].dial_active():
            if time.time() - self._hidden_since > KEEPALIVE_S:
                QApplication.quit()       # free ~70 MB; the service restarts us on demand
                return
        tl = self.pages["timeline"]
        if self.isVisible() or tl.dial_active():
            tl.poll()

    def _travel_done(self, result: str):
        if self._by_dial:                 # the dial opened us — get out of the way
            self._by_dial = False
            self.hide()

    def hideEvent(self, e):
        self._hidden_since = time.time()
        super().hideEvent(e)

    def closeEvent(self, e):
        if self.persistent:
            e.ignore(); self.hide()       # stay warm in the background → instant next time
        else:
            super().closeEvent(e)

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
        page = self.pages[key]
        if hasattr(page, "refresh") and self.stack.currentWidget() is not page:
            page.refresh()                # fresh data whenever a page is opened
        for k, b in self.navs.items():
            b.setChecked(k == key)
            self.nav_icons[k].color = QColor(T["text"] if k == key else T["text3"])
            self.nav_icons[k].update()
        self.stack.setCurrentWidget(self.pages[key])
        self.title.setText(dict((k, t) for k, t, _ in self.TABS)[key])

    def _set_clock(self):
        self.clock.setText(datetime.now().strftime("%A, %d %B").upper())
        self.clock.setFont(font(12, QFont.Weight.DemiBold))

    def _tick(self):
        if not self.isVisible():
            return                        # no work at all while hidden
        self._set_clock()
        page = self.stack.currentWidget()
        if isinstance(page, Page) and not (hasattr(page, "busy") and page.busy()):
            page.refresh()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            tl = self.pages["timeline"]
            if tl.dial_active() and not tl.demo:
                from deepworkai.ui.timetravel import _send
                _send("TRAVEL_CLOSE")
            self.close()
        elif Qt.Key.Key_1 <= e.key() <= Qt.Key.Key_4 and not isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit)):
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
    _apply_accents(); _resolve_palette()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deep Work AI Hub")
    ap.add_argument("--tab", default="focus", choices=["focus", "timeline", "inbox", "insights"])
    ap.add_argument("--background", action="store_true",
                    help="run as the single persistent UI, hidden until the service asks")
    ap.add_argument("--demo-index", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--filter", default="", help="HIGH|MEDIUM|LOW (inbox)")
    ap.add_argument("--theme", default="auto", choices=["auto", "light", "dark"])
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--screenshot", default="", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    # Crisp at 125 % / 150 % Windows scaling (default rounding makes text soft).
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    _apply_theme(a.theme, app)
    server = None
    if a.background:
        name = f"deepworkai-hub-{getpass_user()}"
        probe = QLocalSocket(); probe.connectToServer(name)
        if probe.waitForConnected(150):
            return 0                       # one UI only — the running one handles commands
        QLocalServer.removeServer(name)
        server = QLocalServer(); server.listen(name)
        app.setQuitOnLastWindowClosed(False)
    w = Hub(a.tab, a.filter.upper(), a.demo, persistent=a.background, demo_index=a.demo_index)
    w._server = server
    if a.screenshot:
        w.show(); app.processEvents()
        w.grab().save(a.screenshot)
        return 0
    if not a.background:
        w.present(a.tab)
    return app.exec()


def getpass_user() -> str:
    import getpass
    try:
        return "".join(c for c in getpass.getuser() if c.isalnum()) or "user"
    except Exception:
        return "user"


if __name__ == "__main__":
    sys.exit(main())
