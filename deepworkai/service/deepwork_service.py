"""
Deep Work AI — Production Service v2
======================================
TCP socket server on 127.0.0.1:57321.
All MX Creative Console commands are handled here.

Full command list:
  CAPTURE             → snapshot workspace
  RESTORE             → restore latest snapshot
  REWIND:<N>          → restore snapshot from N minutes ago
  SHIELD_ON/OFF/TOGGLE→ Focus Shield
  TRIAGE_SHOW         → open Triage Dashboard
  MEETING_TOGGLE/START/END → Meeting Mode
  ANCHOR_SAVE         → save cursor-level context
  ANCHOR_RESTORE      → restore to exact file:line
  JOURNAL_CAPTURE     → open micro-journal overlay
  JOURNAL_SAVE:<text> → save note directly
  JOURNAL_GET         → get current note
  JOURNAL_CLEAR       → clear note
  QUEUE_ADD           → queue interruption + LCD sync
  QUEUE_NOTE:<text>   → queue with note + LCD sync
  QUEUE_LIST          → list pending
  QUEUE_CLEAR         → clear reviewed + LCD sync
  PALETTE:<N>         → run terminal palette slot 0-5
  DEBUG_ACTION:<name> → send debug keyboard shortcut
  COGNITIVE_REWIND    → return context summary
  HAPTIC_PULSE:<N>    → trigger haptic (forwarded to plugin)
  NOTIF_ADD:<src>|<title>|<body> → inject notification
  STATUS              → JSON state dump
  PING                → pong
  OPEN_TRASH          → open Recycle Bin
"""

import ctypes
import json
import os
import logging
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import deep_restore_core as core
import slack_integration as slack
from paths import DATA_DIR

PROJECT_ROOT = Path(__file__).parent.parent.parent
HOST = "127.0.0.1"
PORT = 57321
MAX_CMD_BYTES = 4096
RECV_TIMEOUT  = 10

LOG_FILE = DATA_DIR / "service.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Service] %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("deepwork_service")

# ── State ──────────────────────────────────────────────────────────────────────
_shield_state:  dict = {"active": False}
_service_start: float = time.time()
_triage_proc   = None   # Popen handle for triage dashboard
_haptic_clients: list  = []  # websocket/plugin connections wanting haptic events

# ── Command allowlist ──────────────────────────────────────────────────────────
_VALID_COMMANDS = {
    "CAPTURE", "RESTORE", "SHIELD_ON", "SHIELD_OFF", "SHIELD_TOGGLE",
    "TRIAGE_SHOW", "MEETING_TOGGLE", "MEETING_START", "MEETING_END",
    "ANCHOR_SAVE", "ANCHOR_RESTORE",
    "JOURNAL_CAPTURE", "JOURNAL_GET", "JOURNAL_CLEAR",
    "QUEUE_ADD", "QUEUE_LIST", "QUEUE_CLEAR",
    "COGNITIVE_REWIND",
    "STATUS", "PING", "OPEN_TRASH",
    "WORKFLOW_STATUS", "WHERE_WAS_I", "INSIGHTS",
    "AUTO_CAPTURE_ON", "AUTO_CAPTURE_OFF", "RELEASE_HELD",
    "RESUME", "HUB", "SAVE_SPOT", "TRAVEL_COMMIT", "TRAVEL_CLOSE",
}
_VALID_PREFIX_COMMANDS = {
    "REWIND", "JOURNAL_SAVE", "QUEUE_NOTE", "NOTIF_ADD", "NOTIF_FEEDBACK", "DIAL", "TRAVEL_GO",
    "PALETTE", "DEBUG_ACTION", "HAPTIC_PULSE",
}


def _validate_command(raw: str) -> tuple[str, str]:
    cmd = raw.strip()[:MAX_CMD_BYTES]
    if not cmd:
        raise ValueError("Empty command")
    if ":" in cmd:
        prefix, _, arg = cmd.partition(":")
        prefix = prefix.strip().upper()
        if prefix in _VALID_PREFIX_COMMANDS:
            if prefix == "REWIND":
                if not arg.strip().lstrip("-").isdigit():
                    raise ValueError(f"Non-numeric rewind arg: {arg!r}")
            return prefix, arg.strip()
        raise ValueError(f"Unknown prefix: {prefix!r}")
    cmd_upper = cmd.upper()
    if cmd_upper not in _VALID_COMMANDS:
        raise ValueError(f"Unknown command: {cmd!r}")
    return cmd_upper, ""


# ── Focus Shield enforcement ───────────────────────────────────────────────────
_DISTRACTION_EXES = [
    "spotify.exe", "spotifywebhelper.exe",
    "discord.exe", "discordptb.exe", "discordcanary.exe",
    "whatsapp.exe", "telegram.exe", "telegramdesktop.exe",
    "signal.exe", "line.exe", "viber.exe",
    "steam.exe", "steamwebhelper.exe",
    "epicgameslauncher.exe", "riotclientservices.exe",
    "leagueclient.exe", "battlenet.exe", "origin.exe",
]
_PASS_THROUGH_EXES = {"slack.exe", "msteams.exe", "teams.exe", "outlook.exe"}
_DISTRACTION_WINDOW_KEYWORDS = [
    "spotify", "discord", "whatsapp", "telegram",
    "steam", "netflix", "youtube", "twitter",
    "reddit", "instagram", "facebook", "tiktok",
]


def _kill_exe(exe: str) -> bool:
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/T", "/IM", exe],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


def _close_distraction_windows():
    try:
        user32   = ctypes.windll.user32
        WM_CLOSE = 0x0010

        def _cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = (buf.value or "").lower()
            for kw in _DISTRACTION_WINDOW_KEYWORDS:
                if kw in title:
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                    break
            return True

        CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        user32.EnumWindows(CMPFUNC(_cb), 0)
    except Exception as e:
        log.warning("[SHIELD] Window sweep error: %s", e)


def _enforce_dnd_block():
    killed = 0
    for exe in _DISTRACTION_EXES:
        if exe in _PASS_THROUGH_EXES:
            continue
        if _kill_exe(exe):
            killed += 1
    _close_distraction_windows()
    log.info("[SHIELD] DND enforced: %d processes killed", killed)


def _start_dnd_guard():
    def _guard():
        while _shield_state.get("active"):
            time.sleep(90)
            if _shield_state.get("active"):
                _enforce_dnd_block()
    threading.Thread(target=_guard, daemon=True, name="DndGuard").start()


# ── Command handlers ───────────────────────────────────────────────────────────
def _moment_context() -> dict:
    """What you were doing right now — stored with each snapshot for Time Travel."""
    ctx: dict = {}
    try:
        st = _intel().current_state()
        ctx.update(activity=st.activity, focus_score=st.focus_score,
                   repo=st.repo, branch=st.branch, deep_minutes=st.deep_minutes)
    except Exception:
        pass
    try:
        from deepworkai.features.cognitive_rewind import build_rewind_context
        rw = build_rewind_context(minutes=15)
        ctx["file"] = rw.get("last_ide_file") or ""
        ctx["next_step"] = rw.get("next_step") or ""
        ctx["changed_files"] = ((rw.get("git") or {}).get("changed_files") or [])[:5]
        ctx["tabs"] = rw.get("browser_tabs", [])[:5]
    except Exception:
        pass
    return ctx


def _handle_capture(name: str = "hardware") -> str:
    snap = core.capture_workspace()
    cid  = core.save_snapshot(snap, name, context=_moment_context())
    return (f"OK CAPTURE id={cid[:8]} "
            f"windows={len(snap.get('windows', []))} "
            f"tabs={sum(len(v) for v in snap.get('browsers', {}).values())}")


def _handle_restore() -> str:
    snap, ts, summary = core.load_latest_snapshot()
    if not snap:
        return "ERROR NO_SNAPSHOT"
    threading.Thread(target=core.restore_workspace, args=(snap, ts),
                     daemon=True, name="RestoreThread").start()
    return f"OK RESTORE {summary}"


def _handle_rewind(minutes_str: str) -> str:
    try:
        minutes = max(1, min(int(minutes_str), 480))
    except ValueError:
        return "ERROR INVALID_MINUTES"
    snap, ts, summary = core.load_snapshot_before(minutes)
    if not snap:
        return f"ERROR NO_SNAPSHOT before {minutes}min"
    threading.Thread(target=core.restore_workspace, args=(snap, ts),
                     daemon=True, name="RewindThread").start()
    return f"OK REWIND minutes={minutes} {summary}"


def _handle_shield_on() -> str:
    # Rule of three: entering focus saves the workspace first (in background).
    threading.Thread(target=_handle_capture, daemon=True, name="ShieldCapture").start()
    slack.init()
    result = slack.shield_on(duration_minutes=90)
    _shield_state.update({"active": True, "since": datetime.now().isoformat()})
    _enforce_dnd_block()
    _start_dnd_guard()
    try:
        from deepworkai.features.notification_interceptor import set_shield_state
        set_shield_state(True)
    except Exception:
        pass
    try:
        from deepworkai.features.focus_timer import focus_start
        focus_start()
    except Exception:
        pass
    return f"OK SHIELD_ON dnd={'yes' if result.get('dnd_enabled') else 'no'}"


def _handle_shield_off() -> str:
    result = slack.shield_off()
    _shield_state.update({"active": False})
    try:
        from deepworkai.features.notification_interceptor import set_shield_state
        set_shield_state(False)
    except Exception:
        pass
    try:
        from deepworkai.features.focus_timer import focus_end
        focus_end()
    except Exception:
        pass
    try:
        from deepworkai.features.notification_classifier import count_by_priority
        c = count_by_priority()
        notif = f"HIGH:{c.get('HIGH',0)} MED:{c.get('MEDIUM',0)} LOW:{c.get('LOW',0)}"
    except Exception:
        notif = "unavailable"
    return f"OK SHIELD_OFF notifications={notif}"


def _handle_shield_toggle() -> str:
    return _handle_shield_off() if _shield_state.get("active") else _handle_shield_on()


def _handle_triage_show(tab: str = "inbox") -> str:
    global _triage_proc
    if _triage_proc and _triage_proc.poll() is None:
        _triage_proc.terminate()          # reopen on the requested tab
    script = PROJECT_ROOT / "deepworkai" / "features" / "triage_dashboard.py"
    if not script.exists():
        return f"ERROR TRIAGE_SHOW missing {script}"
    try:
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        interp  = str(pythonw) if pythonw.exists() else sys.executable
        _triage_proc = subprocess.Popen(
            [interp, str(script), "--tab", tab],
            cwd=str(PROJECT_ROOT),
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return f"OK TRIAGE_SHOW pid={_triage_proc.pid}"
    except Exception as e:
        return f"ERROR TRIAGE_SHOW {e}"


# Meeting Mode
def _handle_meeting_toggle() -> str:
    from deepworkai.features.meeting_mode import toggle_meeting
    return f"OK MEETING_TOGGLE {toggle_meeting()}"

def _handle_meeting_start() -> str:
    from deepworkai.features.meeting_mode import meeting_start
    return f"OK MEETING_START {meeting_start()}"

def _handle_meeting_end() -> str:
    from deepworkai.features.meeting_mode import meeting_end
    return f"OK MEETING_END {meeting_end()}"


# Context Anchor
def _handle_anchor_save() -> str:
    from deepworkai.features.context_anchor import save_anchor
    return f"OK ANCHOR_SAVE {save_anchor()}"

def _handle_anchor_restore() -> str:
    from deepworkai.features.context_anchor import restore_anchor
    return f"OK ANCHOR_RESTORE {restore_anchor()}"


# Journal
def _handle_journal_capture() -> str:
    from deepworkai.features.micro_journal import launch_overlay
    launch_overlay()
    return "OK JOURNAL_CAPTURE overlay launched"

def _handle_journal_save(text: str) -> str:
    from deepworkai.features.micro_journal import save_note
    save_note(text)
    return "OK JOURNAL_SAVE"

def _handle_journal_get() -> str:
    from deepworkai.features.micro_journal import get_note
    note = get_note()
    return f"OK JOURNAL_GET {note or '(empty)'}"

def _handle_journal_clear() -> str:
    from deepworkai.features.micro_journal import clear_note
    clear_note()
    return "OK JOURNAL_CLEAR"


# Queue
def _handle_queue_add(note: str = "") -> str:
    from deepworkai.features.smart_queue import add_item_and_sync
    count = add_item_and_sync(source="hardware", note=note)
    return f"OK QUEUE_ADD queued={count}"

def _handle_queue_list() -> str:
    from deepworkai.features.smart_queue import get_pending
    return "OK QUEUE_LIST " + json.dumps(get_pending())

def _handle_queue_clear() -> str:
    from deepworkai.features.smart_queue import clear_reviewed_and_sync
    clear_reviewed_and_sync()
    return "OK QUEUE_CLEAR"


# Terminal Palette
def _handle_palette(slot_str: str) -> str:
    from deepworkai.features.terminal_palette import run_slot
    try:
        slot = int(slot_str.strip())
    except ValueError:
        return "ERROR PALETTE invalid slot"
    return f"OK PALETTE {run_slot(slot)}"


# Debug Surface
def _handle_debug_action(action: str) -> str:
    from deepworkai.features.debug_surface import execute_debug_action
    return f"OK DEBUG_ACTION {execute_debug_action(action)}"


# Cognitive Rewind
def _handle_cognitive_rewind() -> str:
    try:
        from deepworkai.features.cognitive_rewind import build_rewind_context
        ctx = build_rewind_context(minutes=15)
        _handle_triage_show("focus")      # show it on screen, not just to the plugin
        return "OK COGNITIVE_REWIND " + json.dumps(ctx)
    except Exception as e:
        return f"ERROR COGNITIVE_REWIND {e}"


# Haptic Pulse (forwarded — plugin reads it in response)
def _handle_haptic_pulse(count_str: str) -> str:
    try:
        count = max(1, min(int(count_str or "1"), 5))
    except ValueError:
        count = 1
    log.info("[HAPTIC] Pulse x%d", count)
    # Plugin receives this response and fires hardware haptic
    return f"OK HAPTIC_PULSE count={count}"


# Notification inject
def _handle_notif_add(arg: str) -> str:
    parts  = arg.split("|", 2)
    source = parts[0].strip() if len(parts) > 0 else "manual"
    title  = parts[1].strip() if len(parts) > 1 else arg
    body   = parts[2].strip() if len(parts) > 2 else ""
    try:
        from deepworkai.features.notification_interceptor import add_manual
        n = add_manual(source=source, title=title, body=body)
        return f"OK NOTIF_ADD id={n['id'][:8]} priority={n['priority']}"
    except Exception as e:
        return f"ERROR NOTIF_ADD {e}"


# Status
def _handle_status() -> str:
    recent = core.get_recent_snapshots(limit=3)
    try:
        from deepworkai.features.notification_classifier import count_by_priority
        notifs = count_by_priority()
    except Exception:
        notifs = {}
    try:
        from deepworkai.features.meeting_mode import get_status as meeting_status
        meeting = meeting_status()
    except Exception:
        meeting = {}
    try:
        from deepworkai.features.focus_timer import get_elapsed_minutes
        focus_min = get_elapsed_minutes()
    except Exception:
        focus_min = 0
    try:
        from deepworkai.service.lcd_state import read_state
        lcd = read_state()
    except Exception:
        lcd = {}
    payload = {
        "shield_active":    _shield_state.get("active", False),
        "focus_minutes":    focus_min,
        "uptime_seconds":   int(time.time() - _service_start),
        "recent_snapshots": recent,
        "notifications":    notifs,
        "meeting":          meeting,
        "lcd":              lcd,
    }
    try:
        payload["workflow"] = _intel().current_state().to_dict()
    except Exception:
        pass
    return "OK STATUS " + json.dumps(payload)


# Workflow intelligence (local AI)
def _intel():
    from deepworkai.features import workflow_intelligence as wi
    return wi


def _handle_save_spot() -> str:
    """Focus key x3: snapshot the workspace and anchor the exact file:line."""
    cap = _handle_capture()
    try:
        anchor = _handle_anchor_save()
    except Exception as e:
        anchor = f"anchor unavailable ({e})"
    return f"OK SAVE_SPOT {cap[3:]} | {anchor[3:]}"


def _handle_resume() -> str:
    """Resume key: restore workspace, jump back to the anchored line, show 'where was I'."""
    result = _handle_restore()

    def _anchor_later():
        time.sleep(2.5)                    # let windows come back first
        try:
            _handle_anchor_restore()
        except Exception as e:
            log.debug("[RESUME] anchor restore: %s", e)
    threading.Thread(target=_anchor_later, daemon=True, name="ResumeAnchor").start()
    _handle_triage_show("focus")
    return result.replace("RESTORE", "RESUME", 1)


def _handle_hub() -> str:
    """Inbox key: open the Hub on Inbox if anything is waiting, else Focus."""
    waiting = 0
    try:
        from deepworkai.features.notification_classifier import count_by_priority
        waiting = sum(count_by_priority().values())
    except Exception:
        pass
    return _handle_triage_show("inbox" if waiting else "focus").replace("TRIAGE_SHOW", "HUB", 1)


# ── Time Travel (dial + overlay) ───────────────────────────────────────────────
TRAVEL_FILE = DATA_DIR / "timetravel.json"
TRAVEL_SPAN = 40                              # snapshots reachable on the dial
_travel = {"items": [], "index": -1, "open": False}
_travel_proc = None


def _travel_write(**extra):
    state = {"index": _travel["index"], "ids": [i["id"] for i in _travel["items"]],
             "open": _travel["open"], "updated": time.time(), **extra}
    try:
        tmp = TRAVEL_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(TRAVEL_FILE)              # atomic: overlay never reads half a file
    except Exception as e:
        log.debug("[TRAVEL] state write: %s", e)


def _travel_show_overlay():
    global _travel_proc
    if _travel_proc and _travel_proc.poll() is None:
        return
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    interp  = str(pythonw) if pythonw.exists() else sys.executable
    try:
        _travel_proc = subprocess.Popen(
            [interp, "-m", "deepworkai.ui.timetravel"], cwd=str(PROJECT_ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        log.warning("[TRAVEL] overlay failed: %s", e)


def _travel_step(tick: int) -> str:
    """Counter-clockwise (tick<0) = further back; clockwise = towards now."""
    if not _travel["open"]:
        _travel["items"] = core.get_recent_snapshots(limit=TRAVEL_SPAN)
        _travel["index"] = -1                 # -1 = "Now" (nothing to restore)
        _travel["open"] = True
    n = len(_travel["items"])
    _travel["index"] = max(-1, min(n - 1, _travel["index"] - tick))
    _travel_write()
    _travel_show_overlay()
    return f"OK DIAL travel index={_travel['index']} of={n}"


def _travel_restore(cid: str) -> str:
    snap, ts, summary = core.load_snapshot_by_id(cid)
    if not snap:
        return f"ERROR TRAVEL no snapshot {cid[:8]}"
    threading.Thread(target=core.restore_workspace, args=(snap, ts),
                     daemon=True, name="TravelRestore").start()
    return f"OK TRAVEL restored {ts} {summary}"


def _handle_travel_commit() -> str:
    """Dial stopped: restore the selected moment (or cancel if on 'Now')."""
    if not _travel["open"]:
        return "OK TRAVEL idle"
    idx, items = _travel["index"], _travel["items"]
    _travel["open"] = False
    if idx < 0 or idx >= len(items):
        _travel_write(result="cancel")
        return "OK TRAVEL cancel"
    _travel_write(result="restore", restored=items[idx]["id"])
    return _travel_restore(items[idx]["id"])


def _handle_travel_go(cid: str) -> str:
    """Overlay click: restore a specific snapshot."""
    _travel["open"] = False
    _travel_write(result="restore", restored=cid)
    return _travel_restore(cid.strip())


def _handle_travel_close() -> str:
    _travel["open"] = False
    _travel_write(result="cancel")
    return "OK TRAVEL closed"


def _auto_snapshot_loop():
    """Every 10 min while you're actually working, keep a moment for Time Travel."""
    last_sig = None
    while True:
        time.sleep(600)
        try:
            st = _intel().current_state()
            if st.activity == "idle":
                continue
            sig = (st.activity, st.repo, st.branch, st.top_app)
            if sig == last_sig and st.focus_score < 60:
                continue                      # nothing new and not deep — skip
            last_sig = sig
            _handle_capture("auto")
            core.prune_auto_snapshots(days=int(os.environ.get("DEEPWORKAI_RETENTION_DAYS", "14")))
        except Exception as e:
            log.debug("[TRAVEL] auto snapshot: %s", e)


def _handle_dial(arg: str) -> str:
    """Context-aware dial: steps the debugger during a debug session, else time travel."""
    try:
        tick = int(arg)
    except ValueError:
        return "ERROR DIAL bad tick"
    try:
        from deepworkai.features import debug_surface
        debugging = debug_surface._active
    except Exception:
        debugging = False
    if debugging and tick:
        from deepworkai.features.debug_surface import execute_debug_action
        action = "Step Over" if tick > 0 else "Step Out"
        for _ in range(min(abs(tick), 5)):
            execute_debug_action(action)
        return f"OK DIAL debug {action}"
    if tick == 0:
        return "OK DIAL travel noop"
    return _travel_step(tick)


def _handle_workflow_status() -> str:
    wi = _intel()
    return "OK WORKFLOW " + json.dumps(wi.current_state().to_dict())


def _handle_where_was_i() -> str:
    ctx = _intel().last_auto_context()
    if not ctx:
        return "OK WHERE_WAS_I nothing captured yet"
    return f"OK WHERE_WAS_I {ctx['summary']} | {ctx.get('anchor', '')}"


def _handle_insights() -> str:
    return "OK INSIGHTS " + json.dumps(_intel().insights())


def _handle_release_held() -> str:
    items = _intel().release_held(include_batched=True)
    return f"OK RELEASE_HELD {len(items)}"


def _handle_notif_feedback(arg: str) -> str:
    # NOTIF_FEEDBACK:<sender>|opened  or  <sender>|ignored
    sender, _, verdict = arg.partition("|")
    _intel().record_feedback(sender.strip(), verdict.strip().lower() == "opened")
    return "OK NOTIF_FEEDBACK"


# ── Main dispatch ──────────────────────────────────────────────────────────────
def handle_command(raw: str) -> str:
    try:
        command, arg = _validate_command(raw)
    except ValueError as e:
        log.warning("[CMD] Rejected: %s — %s", raw[:80], e)
        return f"ERROR INVALID_COMMAND {e}"

    log.info("[CMD] %s %s", command, arg[:60] if arg else "")
    try:
        # Workspace
        if command == "CAPTURE":          return _handle_capture()
        if command == "RESTORE":          return _handle_restore()
        if command == "REWIND":           return _handle_rewind(arg)
        # Shield
        if command == "SHIELD_ON":        return _handle_shield_on()
        if command == "SHIELD_OFF":       return _handle_shield_off()
        if command == "SHIELD_TOGGLE":    return _handle_shield_toggle()
        # Triage
        if command == "TRIAGE_SHOW":      return _handle_triage_show()
        # Meeting
        if command == "MEETING_TOGGLE":   return _handle_meeting_toggle()
        if command == "MEETING_START":    return _handle_meeting_start()
        if command == "MEETING_END":      return _handle_meeting_end()
        # Anchor
        if command == "ANCHOR_SAVE":      return _handle_anchor_save()
        if command == "ANCHOR_RESTORE":   return _handle_anchor_restore()
        # Journal
        if command == "JOURNAL_CAPTURE":  return _handle_journal_capture()
        if command == "JOURNAL_SAVE":     return _handle_journal_save(arg)
        if command == "JOURNAL_GET":      return _handle_journal_get()
        if command == "JOURNAL_CLEAR":    return _handle_journal_clear()
        # Queue
        if command == "QUEUE_ADD":        return _handle_queue_add()
        if command == "QUEUE_NOTE":       return _handle_queue_add(note=arg)
        if command == "QUEUE_LIST":       return _handle_queue_list()
        if command == "QUEUE_CLEAR":      return _handle_queue_clear()
        # Terminal palette
        if command == "PALETTE":          return _handle_palette(arg)
        # Debug surface
        if command == "DEBUG_ACTION":     return _handle_debug_action(arg)
        # Cognitive
        if command == "COGNITIVE_REWIND": return _handle_cognitive_rewind()
        # Haptic
        if command == "HAPTIC_PULSE":     return _handle_haptic_pulse(arg)
        # Notif
        if command == "NOTIF_ADD":        return _handle_notif_add(arg)
        # Status
        if command == "RESUME":           return _handle_resume()
        if command == "SAVE_SPOT":        return _handle_save_spot()
        if command == "DIAL":             return _handle_dial(arg)
        if command == "TRAVEL_COMMIT":    return _handle_travel_commit()
        if command == "TRAVEL_GO":        return _handle_travel_go(arg)
        if command == "TRAVEL_CLOSE":     return _handle_travel_close()
        if command == "HUB":              return _handle_hub()
        if command == "WORKFLOW_STATUS":  return _handle_workflow_status()
        if command == "WHERE_WAS_I":      return _handle_where_was_i()
        if command == "INSIGHTS":         return _handle_insights()
        if command == "RELEASE_HELD":     return _handle_release_held()
        if command == "AUTO_CAPTURE_ON":  _intel().set_auto_capture(True);  return "OK AUTO_CAPTURE on"
        if command == "AUTO_CAPTURE_OFF": _intel().set_auto_capture(False); return "OK AUTO_CAPTURE off"
        if command == "NOTIF_FEEDBACK":   return _handle_notif_feedback(arg)
        if command == "STATUS":           return _handle_status()
        if command == "PING":             return "OK PONG"
        if command == "OPEN_TRASH":
            core.open_recycle_bin()
            return "OK OPEN_TRASH"
    except Exception as e:
        log.exception("[CMD] Handler crashed for %s: %s", command, e)
        return f"ERROR INTERNAL {type(e).__name__}: {e}"

    return f"ERROR UNHANDLED {command}"


# ── TCP Server ────────────────────────────────────────────────────────────────
def _handle_client(conn: socket.socket):
    try:
        conn.settimeout(RECV_TIMEOUT)
        data = b""
        while len(data) < MAX_CMD_BYTES:
            chunk = conn.recv(256)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        if not data:
            return
        raw      = data.decode("utf-8", errors="ignore").split("\n")[0]
        response = handle_command(raw)
        conn.sendall((response + "\n").encode("utf-8"))
    except socket.timeout:
        pass
    except Exception as e:
        log.error("[CLIENT] %s", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    log.info("=" * 60)
    log.info("Deep Work AI Service v2 — port %d", PORT)

    core.init_db()
    slack.init()

    # Pre-warm ML classifier
    def _warm():
        try:
            from deepworkai.features.notification_classifier import _build_model
            _build_model()
            log.info("[CLASSIFIER] Model ready")
        except Exception as e:
            log.debug("[CLASSIFIER] Warm-up: %s", e)
    threading.Thread(target=_warm, daemon=True, name="ClassifierWarmup").start()

    # Activity recorder + workflow intelligence (all local, no network)
    try:
        from deepworkai.activity.recorder import record_loop
        threading.Thread(target=record_loop, daemon=True, name="ActivityRecorder").start()
        from deepworkai.features import workflow_intelligence as wi
        wi.start()
        log.info("[INTEL] recorder + workflow engine running")
    except Exception as e:
        log.error("[INTEL] failed to start: %s", e)

    threading.Thread(target=_auto_snapshot_loop, daemon=True, name="AutoSnapshot").start()

    # Blocker Radar, Git Pulse, Debug watcher, palette — run here so they work
    # no matter how the service was started (plugin auto-spawn or start.py).
    for mod, fn in (("blocker_radar", "start_radar"), ("git_pulse", "start_git_pulse"),
                    ("debug_surface", "start_debug_watcher"), ("terminal_palette", "load_palette")):
        try:
            getattr(__import__(f"deepworkai.features.{mod}", fromlist=[fn]), fn)()
            log.info("[START] %s ready", mod)
        except Exception as e:
            log.warning("[START] %s unavailable: %s", mod, e)

    # LCD state initial write
    try:
        from deepworkai.service.lcd_state import _write
        _write()
    except Exception:
        pass

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
    except OSError as e:
        log.critical("Cannot bind %s:%d — %s", HOST, PORT, e)
        sys.exit(1)
    server.listen(10)
    log.info("Listening on %s:%d", HOST, PORT)

    def _shutdown(sig, frame):
        log.info("Shutting down…")
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(
                target=_handle_client, args=(conn,),
                daemon=True, name=f"Client-{addr[1]}",
            ).start()
        except OSError:
            break
        except Exception as e:
            log.error("[SERVER] Accept error: %s", e)


if __name__ == "__main__":
    main()
