"""
Deep Work AI — Triage Dashboard
=================================
A rich dark-mode "Holding Tank" overlay that surfaces prioritised
notifications (Slack, Jira, GitHub) captured during a Focus Shield session.

Usage
-----
  python triage_dashboard.py
  python triage_dashboard.py --filter HIGH
  python triage_dashboard.py --demo
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import font as tkfont

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Classifier import (optional — dashboard runs without it in demo mode) ──────
try:
    from deepworkai.features.notification_classifier import (
        get_all_unreviewed, mark_reviewed, count_by_priority,
        HIGH, MEDIUM, LOW,
    )
    _CLASSIFIER_OK = True
except ImportError:
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"
    _CLASSIFIER_OK = False


# ── Helpers ────────────────────────────────────────────────────────────────────
def _fmt_ago(minutes: int) -> str:
    return (datetime.now() - timedelta(minutes=minutes)).isoformat()


def _relative_time(iso: str) -> str:
    """Convert ISO timestamp to human-readable '5 min ago'."""
    try:
        dt    = datetime.fromisoformat(iso)
        delta = datetime.now() - dt
        secs  = int(delta.total_seconds())
        if secs < 60:    return "just now"
        if secs < 3600:  return f"{secs // 60} min ago"
        if secs < 86400: return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return ""


# ── Demo data ──────────────────────────────────────────────────────────────────
_DEMO_ITEMS: list[dict] = [
    {"id": "d1", "source": "jira",   "priority": "HIGH",
     "title": "PROD-1923 — API gateway 500 errors on /orders",
     "body":  "All order requests failing since 14:32. 47 customers affected. URGENT.",
     "sender": "incident-bot", "channel": "#incidents", "url": "",
     "confidence": 0.97, "arrived_at": None, "held": True},
    {"id": "d2", "source": "github", "priority": "HIGH",
     "title": "PR #412 — Hotfix: null-check on payment processor",
     "body":  "Review needed urgently before prod deploy at 3pm. Blocking release.",
     "sender": "john", "channel": "", "url": "",
     "confidence": 0.92, "arrived_at": None, "held": True},
    {"id": "d3", "source": "slack",  "priority": "HIGH",
     "title": "CEO: dashboard not loading before client demo",
     "body":  "@here — client arrives in 45 min, charts broken on prod.",
     "sender": "alice", "channel": "#exec", "url": "",
     "confidence": 0.89, "arrived_at": None, "held": True},
    {"id": "d4", "source": "jira",   "priority": "MEDIUM",
     "title": "FEAT-304 — Add dark-mode toggle to settings",
     "body":  "Sprint 22. Story 3 points. Assigned to you.",
     "sender": "jira-bot", "channel": "", "url": "",
     "confidence": 0.74, "arrived_at": None, "held": True},
    {"id": "d5", "source": "github", "priority": "MEDIUM",
     "title": "PR #408 — Refactor auth middleware (review requested)",
     "body":  "Please review when you get a chance. No rush.",
     "sender": "sarah", "channel": "", "url": "",
     "confidence": 0.71, "arrived_at": None, "held": True},
    {"id": "d6", "source": "slack",  "priority": "MEDIUM",
     "title": "Design feedback on onboarding flow",
     "body":  "Hey, could you look at the Figma and leave some thoughts?",
     "sender": "design-team", "channel": "#design", "url": "",
     "confidence": 0.68, "arrived_at": None, "held": True},
    {"id": "d7", "source": "slack",  "priority": "LOW",
     "title": "Team lunch Friday at Yard House — sign up!",
     "body":  "RSVP in the thread below. Totally optional.",
     "sender": "hr-bot", "channel": "#random", "url": "",
     "confidence": 0.91, "arrived_at": None, "held": True},
    {"id": "d8", "source": "jira",   "priority": "LOW",
     "title": "TECH-88 — Update README with new env vars",
     "body":  "Documentation task, low priority, backlog item.",
     "sender": "jira-bot", "channel": "", "url": "",
     "confidence": 0.82, "arrived_at": None, "held": True},
]
# Fill arrived_at now (avoids calling _fmt_ago before function is defined)
_OFFSETS = [2, 15, 8, 40, 55, 62, 90, 120]
for _item, _off in zip(_DEMO_ITEMS, _OFFSETS):
    _item["arrived_at"] = _fmt_ago(_off)


# ── Palette ────────────────────────────────────────────────────────────────────
BG_DARK      = "#0d0d0f"
BG_CARD      = "#161618"
BG_HOVER     = "#1e1e22"
BG_HEADER    = "#111114"
ACCENT_HIGH  = "#ff4d4d"
ACCENT_MED   = "#f5a623"
ACCENT_LOW   = "#4caf8d"
ACCENT_BLUE  = "#4e9eff"
TEXT_PRIMARY = "#f0f0f5"
TEXT_MUTED   = "#8888a0"
TEXT_DIM     = "#555566"
BORDER       = "#25252e"
SHIELD_GREEN = "#00e5a0"

PRIORITY_COLOR = {"HIGH": ACCENT_HIGH, "MEDIUM": ACCENT_MED, "LOW": ACCENT_LOW}
SOURCE_ICON    = {
    "slack":  "💬",
    "jira":   "🎫",
    "github": "🐙",
    "manual": "📝",
}


# ── Main Window ────────────────────────────────────────────────────────────────
class TriageDashboard(tk.Tk):
    def __init__(self, demo: bool = False, filter_priority: str = ""):
        super().__init__()
        self._demo          = demo
        self._items:  list  = []
        self._dismissed: set = set()
        self._active_filter = filter_priority or "ALL"
        self._shield_active = self._check_shield()

        self._setup_window()
        self._setup_fonts()
        self._build_ui()
        self._load_data()
        self._start_refresh_loop()

    # ── Window ────────────────────────────────────────────────────────────
    def _setup_window(self):
        self.title("Deep Work AI — Triage Dashboard")
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w  = min(700, sw // 2)
        h  = min(sh - 60, 880)
        x  = sw - w - 20
        y  = 30
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(520, 400)

        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.97)

        # Drag support
        self.bind("<ButtonPress-1>",   self._drag_start)
        self.bind("<B1-Motion>",       self._drag_move)

    def _drag_start(self, e):
        self._dx = e.x_root - self.winfo_x()
        self._dy = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _setup_fonts(self):
        self._fh1    = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self._ftitle = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._fbody  = tkfont.Font(family="Segoe UI", size=9)
        self._fmeta  = tkfont.Font(family="Segoe UI", size=8)
        self._fbadge = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        self._fbtn   = tkfont.Font(family="Segoe UI", size=8, weight="bold")

    def _check_shield(self) -> bool:
        try:
            import socket as _s
            sock = _s.socket()
            sock.settimeout(0.4)
            sock.connect(("127.0.0.1", 57321))
            sock.sendall(b"STATUS\n")
            data = sock.recv(512).decode("utf-8", errors="ignore")
            sock.close()
            idx = data.find("{")
            if idx != -1:
                return json.loads(data[idx:]).get("shield_active", False)
        except Exception:
            pass
        return False

    # ── UI Build ──────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG_HEADER, height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        shield_col = SHIELD_GREEN if self._shield_active else TEXT_MUTED
        shield_txt = "🛡  SHIELD ACTIVE" if self._shield_active else "🛡  TRIAGE DASHBOARD"
        self._header_lbl = tk.Label(
            hdr, text=shield_txt, font=self._fh1,
            fg=shield_col, bg=BG_HEADER
        )
        self._header_lbl.pack(side="left", padx=16, pady=14)

        tk.Button(
            hdr, text="✕", font=self._fbtn, fg=TEXT_MUTED, bg=BG_HEADER,
            bd=0, activebackground=BG_HOVER, activeforeground=TEXT_PRIMARY,
            cursor="hand2", command=self.destroy
        ).pack(side="right", padx=12)

        tk.Button(
            hdr, text="↺", font=self._fh1, fg=TEXT_MUTED, bg=BG_HEADER,
            bd=0, activebackground=BG_HOVER, activeforeground=ACCENT_BLUE,
            cursor="hand2", command=self._load_data
        ).pack(side="right", padx=4)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Filter tabs
        tab_row = tk.Frame(self, bg=BG_DARK)
        tab_row.pack(fill="x", padx=12, pady=(10, 4))

        self._tab_btns:  dict = {}
        self._count_vars: dict = {}

        for lbl in ["ALL", "HIGH", "MEDIUM", "LOW"]:
            sv  = tk.StringVar(value=lbl)
            self._count_vars[lbl] = sv
            col = PRIORITY_COLOR.get(lbl, ACCENT_BLUE)
            active = lbl == self._active_filter
            b = tk.Label(
                tab_row, textvariable=sv, font=self._fbadge,
                fg=TEXT_PRIMARY if active else TEXT_MUTED,
                bg=col if active else BG_CARD,
                padx=10, pady=5, cursor="hand2", relief="flat"
            )
            b.pack(side="left", padx=4)
            b.bind("<Button-1>", lambda e, l=lbl: self._set_filter(l))
            self._tab_btns[lbl] = b

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(6, 0))

        # Scrollable list
        outer = tk.Frame(self, bg=BG_DARK)
        outer.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(outer, bg=BG_DARK, highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(outer, orient="vertical", command=self._canvas.yview,
                           troughcolor=BG_DARK, bg=BORDER)
        self._inner = tk.Frame(self._canvas, bg=BG_DARK)

        self._inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )
        self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._canvas.bind_all(
            "<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-(e.delta // 120), "units")
        )

        # Footer
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        footer = tk.Frame(self, bg=BG_HEADER, height=42)
        footer.pack(fill="x")
        footer.pack_propagate(False)

        self._status_var = tk.StringVar(value="Loading…")
        tk.Label(footer, textvariable=self._status_var, font=self._fmeta,
                 fg=TEXT_MUTED, bg=BG_HEADER).pack(side="left", padx=14)

        tk.Button(
            footer, text="Dismiss ALL", font=self._fbtn,
            fg=TEXT_MUTED, bg=BG_HEADER, bd=0,
            activebackground=BG_HOVER, activeforeground=ACCENT_HIGH,
            cursor="hand2", command=self._dismiss_all
        ).pack(side="right", padx=12)

    # ── Data ──────────────────────────────────────────────────────────────
    def _load_data(self):
        if self._demo or not _CLASSIFIER_OK:
            raw = _DEMO_ITEMS
        else:
            try:
                raw = get_all_unreviewed(limit=60)
            except Exception:
                raw = _DEMO_ITEMS

        self._items = [i for i in raw if i["id"] not in self._dismissed]
        self._render_cards()
        self._update_tabs()

    def _filtered(self) -> list:
        if self._active_filter == "ALL":
            return self._items
        return [i for i in self._items if i.get("priority") == self._active_filter]

    def _update_tabs(self):
        counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for i in self._items:
            p = i.get("priority", "MEDIUM")
            if p in counts:
                counts[p] += 1
        total = sum(counts.values())

        self._count_vars["ALL"].set(f"ALL  {total}")
        for p, c in counts.items():
            self._count_vars[p].set(f"{p}  {c}")

        shield_txt = "Shield active 🛡" if self._shield_active else "Idle"
        self._status_var.set(
            f"{counts['HIGH']} HIGH · {counts['MEDIUM']} MED · {counts['LOW']} LOW"
            f"   —   {shield_txt}"
        )
        # Update header colour too
        col = SHIELD_GREEN if self._shield_active else TEXT_MUTED
        txt = "🛡  SHIELD ACTIVE" if self._shield_active else "🛡  TRIAGE DASHBOARD"
        self._header_lbl.configure(fg=col, text=txt)

    # ── Cards ─────────────────────────────────────────────────────────────
    def _render_cards(self):
        for w in self._inner.winfo_children():
            w.destroy()

        items = self._filtered()
        if not items:
            tk.Label(
                self._inner, text="✅  You're all caught up",
                font=self._ftitle, fg=TEXT_DIM, bg=BG_DARK
            ).pack(pady=80)
            return

        for item in items:
            self._make_card(item)

    def _make_card(self, item: dict):
        priority = item.get("priority", "MEDIUM")
        pcolor   = PRIORITY_COLOR.get(priority, ACCENT_MED)
        source   = item.get("source", "manual")
        icon     = SOURCE_ICON.get(source, "📣")
        conf     = int(item.get("confidence", 0.5) * 100)
        ago      = _relative_time(item.get("arrived_at") or "")
        held     = bool(item.get("held"))
        url      = item.get("url", "")

        card  = tk.Frame(self._inner, bg=BG_CARD, pady=0)
        card.pack(fill="x", padx=10, pady=4)

        # Left priority stripe
        tk.Frame(card, bg=pcolor, width=5).pack(side="left", fill="y")

        inner = tk.Frame(card, bg=BG_CARD, padx=10, pady=9)
        inner.pack(side="left", fill="both", expand=True)

        # Row 1 — badge row
        r1 = tk.Frame(inner, bg=BG_CARD)
        r1.pack(fill="x")

        tk.Label(r1, text=icon, font=self._ftitle, fg=TEXT_PRIMARY,
                 bg=BG_CARD).pack(side="left")
        tk.Label(r1, text=f"  {priority} ", font=self._fbadge,
                 fg=BG_DARK, bg=pcolor, padx=3).pack(side="left", padx=(4, 0))
        tk.Label(r1, text=f"  {source.upper()}", font=self._fmeta,
                 fg=TEXT_MUTED, bg=BG_CARD).pack(side="left")
        tk.Label(r1, text=f"  {conf}% conf", font=self._fmeta,
                 fg=TEXT_DIM, bg=BG_CARD).pack(side="left")
        if held:
            tk.Label(r1, text="  🔒", font=self._fmeta,
                     fg=TEXT_DIM, bg=BG_CARD).pack(side="left")

        # Row 2 — title
        wrap = self.winfo_width() - 120 if self.winfo_width() > 200 else 500
        tk.Label(
            inner, text=item.get("title", "(no title)"),
            font=self._ftitle, fg=TEXT_PRIMARY, bg=BG_CARD,
            anchor="w", wraplength=wrap, justify="left"
        ).pack(fill="x", pady=(4, 0))

        # Row 3 — body
        body = (item.get("body") or "").strip()
        if body:
            display = body[:180] + ("…" if len(body) > 180 else "")
            tk.Label(
                inner, text=display, font=self._fbody,
                fg=TEXT_MUTED, bg=BG_CARD,
                anchor="w", wraplength=wrap, justify="left"
            ).pack(fill="x", pady=(2, 0))

        # Row 4 — meta + actions
        r4 = tk.Frame(inner, bg=BG_CARD)
        r4.pack(fill="x", pady=(6, 0))

        sender  = item.get("sender", "")
        channel = item.get("channel", "")
        meta    = "  ·  ".join(filter(None, [
            f"@{sender}"  if sender  else "",
            f"#{channel}" if channel else "",
            ago,
        ]))
        tk.Label(r4, text=meta, font=self._fmeta,
                 fg=TEXT_DIM, bg=BG_CARD).pack(side="left")

        tk.Button(
            r4, text="Dismiss", font=self._fbtn,
            fg=TEXT_MUTED, bg=BG_CARD, bd=0,
            activebackground=BG_HOVER, activeforeground=ACCENT_HIGH,
            cursor="hand2",
            command=lambda iid=item["id"]: self._dismiss(iid)
        ).pack(side="right", padx=(4, 0))

        if url:
            tk.Button(
                r4, text="Open ↗", font=self._fbtn,
                fg=ACCENT_BLUE, bg=BG_CARD, bd=0,
                activebackground=BG_HOVER, activeforeground=ACCENT_BLUE,
                cursor="hand2",
                command=lambda u=url: self._open_url(u)
            ).pack(side="right")

        # Hover
        for widget in (card, inner):
            widget.bind("<Enter>", lambda e, c=card, i=inner:
                        (c.configure(bg=BG_HOVER), i.configure(bg=BG_HOVER)))
            widget.bind("<Leave>", lambda e, c=card, i=inner:
                        (c.configure(bg=BG_CARD), i.configure(bg=BG_CARD)))

        tk.Frame(self._inner, bg=BORDER, height=1).pack(fill="x", padx=10)

    # ── Actions ───────────────────────────────────────────────────────────
    def _set_filter(self, label: str):
        self._active_filter = label
        for lbl, btn in self._tab_btns.items():
            col    = PRIORITY_COLOR.get(lbl, ACCENT_BLUE)
            active = lbl == self._active_filter
            btn.configure(
                fg=TEXT_PRIMARY if active else TEXT_MUTED,
                bg=col         if active else BG_CARD,
            )
        self._render_cards()

    def _dismiss(self, item_id: str):
        self._dismissed.add(item_id)
        if _CLASSIFIER_OK and not self._demo:
            try:
                mark_reviewed(item_id)
            except Exception:
                pass
        self._items = [i for i in self._items if i["id"] != item_id]
        self._render_cards()
        self._update_tabs()

    def _dismiss_all(self):
        for item in list(self._items):
            self._dismiss(item["id"])

    def _open_url(self, url: str):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    # ── Refresh loop ──────────────────────────────────────────────────────
    def _start_refresh_loop(self):
        def _loop():
            while True:
                time.sleep(30)
                try:
                    self._shield_active = self._check_shield()
                    self.after(0, self._load_data)
                except Exception:
                    pass
        threading.Thread(target=_loop, daemon=True, name="TriageRefresh").start()


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Deep Work AI — Triage Dashboard")
    ap.add_argument("--demo",   action="store_true", help="Load demo data")
    ap.add_argument("--filter", default="",          help="HIGH|MEDIUM|LOW")
    args = ap.parse_args()

    app = TriageDashboard(demo=args.demo, filter_priority=args.filter.upper())
    app.mainloop()


if __name__ == "__main__":
    main()
