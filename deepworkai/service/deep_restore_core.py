"""
Deep Work AI — Production Restore Core
=======================================
Dynamic app detection and workspace restoration via:
  • Live process enumeration (psutil)
  • Windows registry App Paths
  • Known environment variable paths (pattern-based, not named)
  • Filesystem heuristic search (bounded depth)
  • PowerShell Start-Process final fallback

Sphere Re-Threading feature — restores workspace + cognitive
context in < 5 seconds after an interruption.
"""

import ctypes
import glob
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import winreg
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import psutil

# ── Win32 Setup ──────────────────────────────────────────────────────────────
user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ── Paths ─────────────────────────────────────────────────────────────────────
# Keep restore snapshots in the "new layer" data directory.
# This avoids schema collisions with legacy scripts that also use `data/capsules.db`.
# One data folder for the whole app (<repo>/data) — the UI reads snapshots from here.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
from deepworkai.service.paths import DATA_DIR  # one data folder (installed app or repo)
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "capsules.db"
LOG_PATH = DATA_DIR / "service.log"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Core] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("deep_restore_core")

# ── Win32 Structures ──────────────────────────────────────────────────────────
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long), ("top", ctypes.c_long),
        ("right", ctypes.c_long), ("bottom", ctypes.c_long),
    ]

class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint), ("flags", ctypes.c_uint),
        ("showCmd", ctypes.c_uint), ("ptMinPosition", POINT),
        ("ptMaxPosition", POINT), ("rcNormalPosition", RECT),
    ]

# ── Dynamic Process Classification ────────────────────────────────────────────
# Processes are classified by observable properties.

# Kernel/system process patterns (these can never be user apps)
_SYSTEM_NAME_PATTERNS = re.compile(
    r"^(system|registry|smss|wininit|winlogon|csrss|services|lsass|"
    r"lsm|svchost|dwm|sihost|taskhostw|runtimebroker|dllhost|"
    r"fontdrvhost|spoolsv|searchindexer|searchhost|wudfhost|"
    r"audiodg|conhost|ctfmon|textinputhost|applicationframehost|"
    r"startmenuexperiencehost|shellexperiencehost|searchapp|"
    r"securityhealthsystray|gamebarpresencewriter|widgets|"
    # Note: do NOT classify explorer.exe as "system" because the product
    # needs to restore File Explorer window layout too.
    r")\.exe$",
    re.IGNORECASE,
)

# Processes that represent shells/runtimes — captured for context but NOT
# blindly relaunched (they'd open and close with no job to do)
_SHELL_RUNTIME_PATTERNS = re.compile(
    r"^(cmd|powershell|pwsh|powershell_ise|wscript|cscript|"
    r"python|pythonw|python3|node|nodejs|ruby|java|javaw|"
    r"dotnet|perl|php|go|rust)\.exe$",
    re.IGNORECASE,
)

# Logitech own processes — never touch
_LOGITECH_PATTERNS = re.compile(
    r"^(logi|lghub|logioptions|logi_options|logioptionsplus|logitune).*?\.exe$",
    re.IGNORECASE,
)

# Browser process names — handled specially for tab capture
_BROWSER_NAMES = {"brave.exe", "chrome.exe", "msedge.exe", "firefox.exe",
                  "opera.exe", "vivaldi.exe", "arc.exe"}

# Terminal emulators — launched with window (not hidden)
_TERMINAL_NAMES = {"windowsterminal.exe", "wt.exe",
                   "conemu64.exe", "hyper.exe", "alacritty.exe"}


def _is_system_process(proc_name: str) -> bool:
    return bool(_SYSTEM_NAME_PATTERNS.match(proc_name))

def _is_shell_runtime(proc_name: str) -> bool:
    return bool(_SHELL_RUNTIME_PATTERNS.match(proc_name))

def _is_logitech(proc_name: str) -> bool:
    return bool(_LOGITECH_PATTERNS.match(proc_name))

def _should_skip(proc_name: str) -> bool:
    n = proc_name.lower()
    # Never capture or relaunch ourselves: a second DeepWorkAI.exe steals the port and key.
    return _is_system_process(n) or _is_logitech(n) or n == "deepworkai.exe"

def _should_skip_relaunch(proc_name: str) -> bool:
    """True for processes we capture for context but never blindly relaunch."""
    n = proc_name.lower()
    return _should_skip(n) or _is_shell_runtime(n)


# ── Database ──────────────────────────────────────────────────────────────────
def init_db():
    """Initialise (or migrate) the capsules database.

    Uses CREATE TABLE IF NOT EXISTS for the base schema, then applies
    ALTER TABLE for any columns added in later versions so that
    existing databases are automatically migrated.
    """
    # A non-database file here (e.g. a Git LFS pointer from a clone without LFS)
    # used to crash every capture/restore. Move it aside and start fresh.
    if DB_PATH.exists():
        with open(DB_PATH, "rb") as fh:
            if fh.read(16) != b"SQLite format 3\x00":
                bad = DB_PATH.with_suffix(".invalid")
                DB_PATH.replace(bad)
                log.warning("[DB] %s was not a database — moved to %s", DB_PATH, bad.name)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    # Base schema (safe for fresh installs)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS capsules (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            timestamp      TEXT NOT NULL,
            workspace_json TEXT NOT NULL,
            summary        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ts ON capsules(timestamp DESC);
    """)

    # Migration: add columns that may be missing in older DBs
    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(capsules)").fetchall()
    }
    migrations = [
        ("context_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("source",       "TEXT DEFAULT 'auto'"),
    ]
    for col_name, col_def in migrations:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE capsules ADD COLUMN {col_name} {col_def}")
            log.info("[DB] Migrated: added column '%s'", col_name)

    conn.commit()
    conn.close()
    log.info("[DB] Schema ready at %s", DB_PATH)


# ── Dynamic EXE Discovery ─────────────────────────────────────────────────────
def find_exe(process_name: str, saved_path: str = "") -> str:
    """
    Locate the full path to an installed .exe using multiple strategies.
    Everything is discovered at runtime.
    Returns full path string or "" if not found.
    """
    name = process_name.lower()
    if not name.endswith(".exe"):
        name += ".exe"

    # Strategy 0 — use saved path if still valid
    if saved_path and Path(saved_path).exists():
        return saved_path

    # Strategy 0.5 — well-known install paths for apps with non-obvious directory names
    # (Insert before live process checks and other heuristics to avoid silent failure.)
    _KNOWN_EXE_PATHS: dict[str, list[str]] = {
        "brave.exe": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "brave-browser.exe": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
        ],
        "code.exe": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Programs", "Microsoft VS Code", "Code.exe"),
            r"C:\Program Files\Microsoft VS Code\Code.exe",
        ],
        "cursor.exe": [
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Programs", "cursor", "Cursor.exe"),
        ],
    }
    for candidate in _KNOWN_EXE_PATHS.get(name, []):
        if candidate and Path(candidate).exists():
            return candidate

    # Strategy 1 — live process: get exe path directly from a running instance
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            if proc.info["name"].lower() == name:
                exe = proc.info.get("exe") or ""
                if exe and Path(exe).exists():
                    return exe
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    # Strategy 2 — Windows App Paths registry (both HKLM and HKCU)
    reg_sub = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, reg_sub) as k:
                val, _ = winreg.QueryValueEx(k, "")
                path = os.path.expandvars(val.strip('"').strip("'"))
                if path and Path(path).exists():
                    return path
        except (FileNotFoundError, OSError):
            pass

    # Strategy 3 — Uninstall registry: read InstallLocation for any registered app
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ):
            try:
                with winreg.OpenKey(root, sub) as parent:
                    count = winreg.QueryInfoKey(parent)[0]
                    for i in range(count):
                        try:
                            sub_name = winreg.EnumKey(parent, i)
                            with winreg.OpenKey(parent, sub_name) as k:
                                try:
                                    loc, _ = winreg.QueryValueEx(k, "InstallLocation")
                                    loc = loc.strip('"').strip("'")
                                    candidate = Path(loc) / name
                                    if candidate.exists():
                                        return str(candidate)
                                    # Also search one level deep
                                    for child in Path(loc).glob(f"**/{name}"):
                                        return str(child)
                                except FileNotFoundError:
                                    pass
                        except OSError:
                            pass
            except OSError:
                pass

    # Strategy 4 — environment-variable-rooted heuristic paths
    # Covers LOCALAPPDATA, APPDATA, PROGRAMFILES, PROGRAMFILES(X86), USERPROFILE
    env_roots = [
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("APPDATA", ""),
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps"),
    ]
    stem = name.replace(".exe", "")   # e.g. "slack"
    for root in env_roots:
        if not root:
            continue
        root_path = Path(root)
        if not root_path.exists():
            continue
        # Direct match: %LOCALAPPDATA%\Slack\slack.exe
        direct = root_path / stem / name
        if direct.exists():
            return str(direct)
        # One folder deeper with glob for versioned dirs and deeper nested paths
        # (Some apps install to paths like BraveSoftware/Brave-Browser/Application/app.exe.)
        for pattern in [
            f"{stem}*/{name}",
            f"{stem}/{stem}*/{name}",
            f"{stem}*/*/{name}",
            f"{stem}*/**/{name}",
        ]:
            matches = sorted(root_path.glob(pattern))
            if matches:
                return str(matches[-1])

    # Strategy 5 — where.exe (PATH-based lookup)
    try:
        result = subprocess.run(
            ["where", name], capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()
            if lines and Path(lines[0]).exists():
                return lines[0]
    except Exception:
        pass

    # Strategy 6 — bounded filesystem search (max depth 6, skips obvious noise)
    search_roots = [r for r in env_roots if r and Path(r).exists()]
    for root in search_roots:
        try:
            for dirpath, dirs, files in os.walk(root):
                depth = dirpath.replace(root, "").count(os.sep)
                if depth > 6:
                    dirs.clear()
                    continue
                # Skip hidden / temp dirs
                dirs[:] = [d for d in dirs if not d.startswith(".") and
                            d.lower() not in ("temp", "tmp", "cache", "logs")]
                if name in (f.lower() for f in files):
                    return os.path.join(dirpath, next(f for f in files
                                                       if f.lower() == name))
        except (PermissionError, OSError):
            pass

    return ""


# ── Browser Tab Capture ───────────────────────────────────────────────────────
_LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
_ROAMING = Path(os.environ.get("APPDATA", ""))
# Where each browser keeps its profiles. Chromium family: every "User Data/<profile>" with a
# Sessions folder. Opera keeps one profile in the folder itself. Firefox: see _firefox_tabs.
_BROWSER_SESSION_PATHS = {
    "brave.exe":   _LOCAL / "BraveSoftware/Brave-Browser/User Data",
    "chrome.exe":  _LOCAL / "Google/Chrome/User Data",
    "msedge.exe":  _LOCAL / "Microsoft/Edge/User Data",
    "vivaldi.exe": _LOCAL / "Vivaldi/User Data",
    "opera.exe":   _ROAMING / "Opera Software/Opera Stable",
    "firefox.exe": _ROAMING / "Mozilla/Firefox/Profiles",
}


def _profile_dirs(browser_exe: str) -> list[Path]:
    base = _BROWSER_SESSION_PATHS.get(browser_exe.lower())
    if not base or not base.exists():
        return []
    if (base / "Sessions").exists() or (base / "Current Session").exists():
        return [base]
    return [d for d in base.iterdir() if (d / "Sessions").exists()]

# Only capture & restore tabs that are developer-relevant.
# Everything else (YouTube, social, shopping) is noise that slows restore.
_DEV_URL_PATTERNS = [
    "jira", "atlassian.net", "confluence",
    "github.com", "gitlab.com", "bitbucket.org",
    "stackoverflow.com", "stackexchange.com",
    "localhost", "127.0.0.1",
    "docs.", "developer.", "api.",
    "console.aws", "console.cloud.google", "portal.azure",
    "linear.app", "notion.so", "figma.com",
    "vercel.app", "netlify.app", "render.com",
    "npmjs.com", "pypi.org", "crates.io",
]

# Bumped when tab capture became accurate. Snapshots without it were captured
# from the recently-closed list and must not have their tabs restored.
TABS_FORMAT = 2

# Max tabs to capture per browser — prevents tab floods on restore
_MAX_TABS_PER_BROWSER = 50


def _read_browser_tabs(browser_exe: str) -> list[dict]:
    """
    Capture the tabs that are open *right now*.
    Replays the live Session_* command log (see chromium_session.py). The old
    code scraped every URL out of Sessions/Tabs_* — Chromium's *recently
    closed* list — which restored tabs closed days or months ago.
    """
    from chromium_session import current_session_file
    if browser_exe.lower() == "firefox.exe":
        tabs = _firefox_tabs()
        log.info("[CAPTURE] %s: %d open tabs captured", browser_exe, len(tabs))
        return tabs, []
    tabs, locked = [], []
    for profile in _profile_dirs(browser_exe):         # every profile, not just Default
        f = current_session_file(profile)
        if not f:
            continue
        got = _tabs_from_session_file(f)
        if got is None:
            # The file is an append-only log: its size now marks this moment, so restore
            # can replay exactly up to here, not whatever was open when the browser closed.
            locked.append({"file": str(f), "size": f.stat().st_size})
        else:
            tabs += got
    log.info("[CAPTURE] %s: %d open tabs captured, %d locked session(s) deferred",
             browser_exe, len(tabs), len(locked))
    return tabs[:_MAX_TABS_PER_BROWSER], locked


def _firefox_tabs() -> list[dict]:
    """Open tabs from Firefox's live session (sessionstore-backups/recovery.jsonlz4, never locked)."""
    from chromium_session import strip_secret_params
    base = _BROWSER_SESSION_PATHS["firefox.exe"]
    files = list(base.glob("*/sessionstore-backups/recovery.jsonlz4")) if base.exists() else []
    if not files:
        return []
    try:
        state = json.loads(_mozlz4(max(files, key=lambda f: f.stat().st_mtime).read_bytes()))
    except (OSError, ValueError):
        return []
    urls = []
    for w in state.get("windows", []):
        for t in w.get("tabs", []):
            entries = t.get("entries") or []
            if entries:
                u = entries[min(max(t.get("index", len(entries)), 1), len(entries)) - 1].get("url", "")
                if u.startswith(("http://", "https://")):
                    urls.append(strip_secret_params(u))
    return [{"url": u, "title": u} for u in urls[:_MAX_TABS_PER_BROWSER]]


def _mozlz4(data: bytes) -> bytes:
    """Decode Firefox's mozLz4 file: 8-byte magic, 4-byte size, then one raw LZ4 block."""
    if data[:8] != b"mozLz40\0":
        raise ValueError("not mozlz4")
    src, out, i = data[12:], bytearray(), 0
    while i < len(src):
        tok = src[i]; i += 1
        n = tok >> 4
        if n == 15:
            while src[i] == 255:
                n += 255; i += 1
            n += src[i]; i += 1
        out += src[i:i + n]; i += n
        if i >= len(src):
            break
        off = src[i] | src[i + 1] << 8; i += 2
        m = tok & 15
        if m == 15:
            while src[i] == 255:
                m += 255; i += 1
            m += src[i]; i += 1
        for _ in range(m + 4):                          # byte by byte: matches may overlap
            out.append(out[-off])
    return bytes(out)


def _tabs_from_session_file(f, size: int | None = None) -> list[dict] | None:
    """Tabs in a session file (up to `size` bytes), or None while the browser holds it locked."""
    from chromium_session import parse_session, strip_secret_params
    try:
        data = Path(f).read_bytes()
        if size and size <= len(data):
            data = data[:size]
    except PermissionError:
        return None
    except OSError:
        return []
    urls = [strip_secret_params(u) for u in parse_session(data)[:_MAX_TABS_PER_BROWSER]]
    return [{"url": u, "title": u} for u in urls]


def _detect_active_browsers() -> list[str]:
    """Return list of browser exe names that are currently running."""
    running_names = {p.info["name"].lower()
                     for p in psutil.process_iter(["name"])}
    return [b for b in _BROWSER_NAMES if b in running_names]


# ── Window Enumeration ────────────────────────────────────────────────────────
def enum_windows() -> list[dict]:
    """
    Enumerate all meaningful visible windows.
    Skips: invisible, untitled, system, Logitech, tiny utility windows.
    Returns list of window dicts with full position + process metadata.
    """
    results: list[dict] = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True

        # Get title
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf    = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title  = buf.value.strip()
        if not title:
            return True

        # Get PID → process info
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc   = psutil.Process(pid.value)
            pname  = proc.name()
            if _should_skip(pname):
                return True
            try:
                exe_path = proc.exe()
            except (psutil.AccessDenied, OSError):
                exe_path = ""
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return True

        # Get window placement
        wp        = WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(wp)
        user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
        rc = wp.rcNormalPosition

        # Skip windows smaller than a usable size (utility/tray popups)
        if rc.right - rc.left < 80 or rc.bottom - rc.top < 60:
            return True

        results.append({
            "hwnd":        hwnd,
            "title":       title[:256],       # cap title length
            "process":     pname,
            "exe_path":    exe_path,
            "show_cmd":    wp.showCmd,
            "is_terminal": pname.lower() in _TERMINAL_NAMES,
            "is_browser":  pname.lower() in _BROWSER_NAMES,
            "pos": {
                "left":   rc.left,
                "top":    rc.top,
                "right":  rc.right,
                "bottom": rc.bottom,
            },
        })
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception as e:
        log.error("[CAPTURE] EnumWindows error: %s", e)

    return results


# ── VS Code Context ───────────────────────────────────────────────────────────
def _get_vscode_context() -> dict:
    """The project folder VS Code/Cursor is working in (decoded, real path)."""
    try:
        from ide_context import active_workspace
    except ImportError:
        from deepworkai.service.ide_context import active_workspace
    return {"workspace_path": active_workspace(), "open_files": []}


# ── Git Context ───────────────────────────────────────────────────────────────
def _get_git_context(workspace_path: str) -> dict:
    """Return branch, changed files, recent commits for a workspace path."""
    ctx: dict = {"branch": "", "changed_files": [], "recent_commits": []}
    if not workspace_path:
        return ctx
    path = workspace_path
    if not Path(path).exists():
        return ctx
    try:
        def _git(*args):
            r = subprocess.run(
                ["git", *args], cwd=path,
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return r.stdout.strip()
        ctx["branch"]         = _git("rev-parse", "--abbrev-ref", "HEAD")
        ctx["changed_files"]  = _git("diff", "--name-only").splitlines()[:10]
        ctx["recent_commits"] = _git("log", "--oneline", "-5").splitlines()
    except Exception:
        pass
    return ctx


# ── Workspace Capture ─────────────────────────────────────────────────────────
def capture_workspace() -> dict:
    """
    Snapshot the full workspace state: windows, browser tabs, VS Code,
    git context, terminal CWDs. Everything is discovered dynamically.
    """
    windows  = enum_windows()
    browsers: dict[str, list] = {}

    # Capture tabs for every running browser
    pending: dict[str, str] = {}
    for bname in _detect_active_browsers():
        tabs, locked = _read_browser_tabs(bname)
        if tabs:
            browsers[bname] = tabs
        if locked:
            pending[bname] = locked         # locked now; they hold these tabs once the browser closes

    vscode = _get_vscode_context()
    git    = _get_git_context(vscode.get("workspace_path", ""))

    # Collect terminal CWDs from running terminal processes
    terminal_cwds: list[str] = []
    for proc in psutil.process_iter(["name", "cwd"]):
        try:
            if proc.info["name"].lower() in _TERMINAL_NAMES:
                cwd = proc.info.get("cwd") or ""
                if cwd and Path(cwd).exists() and cwd not in terminal_cwds:
                    terminal_cwds.append(cwd)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return {
        "windows":       windows,
        "browsers":      browsers,
        "pending_tabs":  pending,
        "vscode":        vscode,
        "git":           git,
        "terminal_cwds": terminal_cwds,
        "tabs_format":   TABS_FORMAT,
        "captured_at":   datetime.now().isoformat(),
    }


def save_snapshot(snapshot: dict, name: str = "auto",
                  context: dict | None = None) -> str:
    """Persist a snapshot to the database. Returns the new capsule ID."""
    cid     = str(uuid.uuid4())
    ts      = datetime.now().isoformat()
    w_count = len(snapshot.get("windows", []))
    b_count = sum(len(v) for v in snapshot.get("browsers", {}).values())
    branch  = snapshot.get("git", {}).get("branch", "—")
    summary = f"{w_count} windows · {b_count} browser tabs · branch: {branch}"

    # If context was provided, merge it into the snapshot blob
    if context:
        snapshot["_context"] = context

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute(
        "INSERT INTO capsules (id, name, timestamp, workspace_json, summary) "
        "VALUES (?,?,?,?,?)",
        (cid, name, ts, json.dumps(snapshot), summary),
    )
    conn.commit()
    conn.close()
    log.info("[DB] Saved capsule %s — %s", cid[:8], summary)
    return cid


def load_latest_snapshot() -> tuple[dict | None, str, str]:
    """Return (snapshot_dict, timestamp, summary) for the most recent capsule."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cur  = conn.cursor()
        cur.execute(
            "SELECT workspace_json, timestamp, summary "
            "FROM capsules ORDER BY timestamp DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None, "", ""
        return json.loads(row[0]), row[1], row[2] or ""
    except Exception as e:
        log.error("[DB] load_latest_snapshot error: %s", e)
        return None, "", ""


def load_snapshot_before(minutes: int) -> tuple[dict | None, str, str]:
    """Return the most recent snapshot captured ≥ `minutes` ago."""
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cur  = conn.cursor()
        cur.execute(
            "SELECT workspace_json, timestamp, summary "
            "FROM capsules WHERE timestamp <= ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (cutoff,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None, "", ""
        return json.loads(row[0]), row[1], row[2] or ""
    except Exception as e:
        log.error("[DB] load_snapshot_before error: %s", e)
        return None, "", ""


def load_snapshot_by_id(cid: str) -> tuple[dict | None, str, str]:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        row = conn.execute("SELECT workspace_json, timestamp, summary FROM capsules WHERE id=?",
                           (cid,)).fetchone()
        conn.close()
        return (json.loads(row[0]), row[1], row[2] or "") if row else (None, "", "")
    except Exception as e:
        log.error("[DB] load_snapshot_by_id error: %s", e)
        return None, "", ""


def prune_auto_snapshots(days: int = 14):
    """Delete automatic snapshots older than `days` (manual ones are kept)."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("DELETE FROM capsules WHERE name='auto' AND timestamp < ?", (cutoff,))
        conn.commit(); conn.close()
    except Exception as e:
        log.debug("[DB] prune error: %s", e)


def get_recent_snapshots(limit: int = 10) -> list[dict]:
    """Return last `limit` snapshot metadata records (no workspace JSON)."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cur  = conn.cursor()
        cur.execute(
            "SELECT id, name, timestamp, summary FROM capsules "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()
        return [{"id": r[0], "name": r[1], "timestamp": r[2], "summary": r[3]}
                for r in rows]
    except Exception as e:
        log.error("[DB] get_recent_snapshots error: %s", e)
        return []


# ── App Launch ────────────────────────────────────────────────────────────────
def _get_currently_open_urls(browser_exe: str) -> set:
    """URLs open in the live browser session — used to avoid duplicate tabs."""
    tabs, _locked = _read_browser_tabs(browser_exe)
    return {t["url"].split("#")[0].rstrip("/") for t in tabs}


def launch_browser(browser_exe: str, tabs: list) -> bool:
    """
    Launch (or reuse) a browser and restore saved tabs.
    Only opens URLs that aren't already open — prevents tab duplication.
    """
    browser_lower = browser_exe.lower()
    all_urls = [t["url"] if isinstance(t, dict) else str(t) for t in tabs]
    # Security: a value starting with '-' would be parsed as a browser flag.
    all_urls = [u for u in all_urls if re.match(r"^https?://[^\s]+$", u)]
    # Safety cap
    all_urls = all_urls[:_MAX_TABS_PER_BROWSER]
    if not all_urls:
        return False

    exe_path = find_exe(browser_lower)
    if not exe_path:
        log.warning("[RESTORE] Cannot find exe for browser: %s", browser_exe)
        return False

    # Check if browser is already running
    running_names = {p.info["name"].lower()
                     for p in psutil.process_iter(["name"])}
    browser_running = browser_lower in running_names

    # ── De-duplicate: only open tabs NOT already visible ────────────────────
    if browser_running:
        open_urls = _get_currently_open_urls(browser_lower)
        urls_to_open = [
            u for u in all_urls
            if u.split("#")[0].rstrip("/") not in open_urls
        ]
        log.info("[RESTORE] %s: %d saved tabs, %d already open, %d to open",
                 browser_exe, len(all_urls), len(open_urls), len(urls_to_open))
    else:
        urls_to_open = all_urls

    if not urls_to_open:
        log.info("[RESTORE] %s: all tabs already open — skipping", browser_exe)
        return True

    try:
        if browser_running:
            # Browser running — open only the missing tabs
            subprocess.Popen(
                [exe_path] + urls_to_open,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            log.info("[RESTORE] Opened %d new tabs in running %s",
                     len(urls_to_open), browser_exe)
        else:
            # Browser not running — launch with all saved tabs in one window
            subprocess.Popen(
                [exe_path, "--new-window"] + urls_to_open,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            log.info("[RESTORE] Launched %s with %d tabs", browser_exe, len(urls_to_open))
        return True
    except Exception as e:
        log.warning("[RESTORE] Browser launch failed %s: %s", browser_exe, e)
        return False


def launch_app(process_name: str, saved_exe_path: str = "") -> bool:
    """
    Launch any desktop application.
    Uses dynamic exe discovery at runtime.
    Falls back to PowerShell Start-Process for Store/UWP apps.
    Never launches shell/runtime processes (cmd, python, etc.).
    """
    name = process_name.lower()

    # Safety: never blindly relaunch shells or runtimes
    if _should_skip_relaunch(name):
        log.debug("[RESTORE] Skipping relaunch of shell/runtime: %s", name)
        return False

    # Special case: Windows Terminal — must be visible
    if name in _TERMINAL_NAMES:
        try:
            subprocess.Popen(
                ["wt"],
                creationflags=0,    # visible window intentional
                shell=False,
            )
            return True
        except Exception:
            pass

    # Dynamic exe discovery
    exe_path = find_exe(name, saved_exe_path)
    if exe_path:
        try:
            subprocess.Popen(
                [exe_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            log.info("[RESTORE] Launched %s from %s", name, exe_path)
            return True
        except Exception as e:
            log.warning("[RESTORE] Direct launch failed for %s: %s", name, e)

    # Final fallback: PowerShell Start-Process (handles UWP, Store, unregistered apps)
    # Only plain executable names — anything else could inject PowerShell.
    if not re.fullmatch(r"[\w.\- ]{1,64}", process_name or ""):
        log.warning("[RESTORE] Refusing PowerShell launch for unsafe name %r", process_name)
        return False
    try:
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command",
             f"Start-Process '{process_name}'"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        log.info("[RESTORE] Launched %s via PowerShell fallback", name)
        return True
    except Exception as e:
        log.error("[RESTORE] All strategies failed for %s: %s", name, e)
        return False


# ── Window Repositioning ──────────────────────────────────────────────────────
def _snapshot_hwnds() -> dict:
    """
    Single-pass EnumWindows: returns a dict of
        process_name_lower -> [ {hwnd, title}, ... ]
    for every visible, titled, non-system top-level window.
    Called ONCE before the reposition loop — no per-window polling.
    """
    result: dict = {}
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = (buf.value or "").strip()
        if not title:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            pname = psutil.Process(pid.value).name().lower()
        except Exception:
            return True
        if _should_skip(pname):
            return True
        result.setdefault(pname, []).append({"hwnd": hwnd, "title": title.lower()})
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception as e:
        log.warning("[RESTORE] _snapshot_hwnds error: %s", e)
    return result


def reposition(hwnd: int, pos: dict, show_cmd: int = 1):
    """
    Atomically restore a window's position and state using SetWindowPlacement.
    SetWindowPlacement is the correct Win32 API for this — it sets both the
    normal position AND the show state in one call, with no DWM flicker.
    SWP_NOACTIVATE is used for SetWindowPos calls to avoid focus fights.
    """
    if not hwnd:
        return

    SW_MAXIMIZE   = 3
    SW_SHOWNORMAL = 1
    SWP_NOZORDER   = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FLAGS      = SWP_NOZORDER | SWP_NOACTIVATE

    left   = pos.get("left",   50)
    top    = pos.get("top",    50)
    right  = pos.get("right",  1280)
    bottom = pos.get("bottom", 720)
    width  = max(right - left, 200)
    height = max(bottom - top, 150)

    try:
        # Use SetWindowPlacement for atomic position + state restore.
        # Build a WINDOWPLACEMENT struct with the saved normal rect.
        wp = WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(wp)
        user32.GetWindowPlacement(hwnd, ctypes.byref(wp))  # read current flags
        wp.showCmd          = show_cmd if show_cmd in (SW_SHOWNORMAL, SW_MAXIMIZE) else SW_SHOWNORMAL
        wp.rcNormalPosition = RECT(left, top, left + width, top + height)
        user32.SetWindowPlacement(hwnd, ctypes.byref(wp))
    except Exception:
        # Fallback: plain SetWindowPos
        user32.SetWindowPos(hwnd, 0, left, top, width, height, SWP_FLAGS)


# ── Main Restore ──────────────────────────────────────────────────────────────
def restore_workspace(snapshot: dict, label: str = ""):
    """
    Fast workspace restore.
    Target: complete in < 8 seconds.

    Phases:
      1. Launch browsers with filtered dev tabs (parallel, max 5 tabs each)
      2. Launch missing desktop apps (skip browsers, already handled)
      3. Brief wait for windows to appear
      4. Reposition windows to saved coordinates (short timeouts)
    """
    windows       = snapshot.get("windows", [])
    browsers      = snapshot.get("browsers", {})
    if browsers and snapshot.get("tabs_format", 1) < TABS_FORMAT:
        log.info("[RESTORE] Skipping browser tabs from legacy snapshot "
                 "(captured from the recently-closed list, not open tabs)")
        browsers = {}

    running = {p.info["name"].lower()
               for p in psutil.process_iter(["name"])}

    # Tabs that were locked at capture: readable now if that browser has since closed.
    browsers = dict(browsers)
    for bname, files in snapshot.get("pending_tabs", {}).items():
        if bname in running:
            continue
        for e in [files] if isinstance(files, str) else files:
            f, size = (e["file"], e.get("size")) if isinstance(e, dict) else (e, None)
            browsers[bname] = list(browsers.get(bname, [])) + (_tabs_from_session_file(f, size) or [])

    log.info("[RESTORE] Starting. %d windows, %d browsers, label=%s",
             len(windows), len(browsers), label)

    # ── Phase 1: Browsers (fast — max 5 tabs each, opened in one call) ────────
    for browser, tabs in browsers.items():
        if tabs:
            launch_browser(browser, tabs)

    # ── Phase 2: Desktop apps ─────────────────────────────────────────────────
    # Count how many instances of each app we have running vs what we need
    current_windows = enum_windows()
    running_counts = {}
    for w in current_windows:
        p = w.get("process", "").lower()
        running_counts[p] = running_counts.get(p, 0) + 1

    needed_counts = {}
    for win in windows:
        p = win.get("process", "").lower()
        if p and not win.get("is_browser") and not _should_skip_relaunch(p):
            needed_counts[p] = needed_counts.get(p, 0) + 1

    for pname, count in needed_counts.items():
        existing = running_counts.get(pname, 0)
        to_launch = count - existing
        
        # Some apps like explorer we might want to launch for each folder if not enough are open
        if to_launch > 0:
            # We don't have the exe_path directly indexed by count, so we'll just find one from the windows list
            exe = next((w.get("exe_path", "") for w in windows if w.get("process", "").lower() == pname), "")
            for _ in range(to_launch):
                result = launch_app(pname, exe)
                log.info("[RESTORE] launch_app(%s) [%d/%d needed] → %s", pname, _ + 1, to_launch,
                         "launched" if result else "failed")
                time.sleep(0.5)

    # ── Phase 3: Wait for newly launched apps to create their windows ─────────
    # Newly launched apps need a moment; already-running apps need almost none.
    # Poll instead of a fixed sleep: continue as soon as every new app has a window.
    newly_launched = (set(needed_counts) | {b for b in browsers if browsers[b]}) - running
    deadline = time.time() + 3.0
    while newly_launched and time.time() < deadline:
        if newly_launched <= set(_snapshot_hwnds()):
            break
        time.sleep(0.1)

    # ── Phase 4: Reposition — ONE snapshot, no polling ────────────────────────
    # Take a single EnumWindows pass to build a complete map of
    #   process_name -> [list of {hwnd, title} dicts]
    # Then match each saved window record to an hwnd from that map.
    # This is O(N) with zero blocking — no per-window timeouts or loops.
    hwnd_map = _snapshot_hwnds()
    log.info("[RESTORE] Phase 4: hwnd map has %d processes", len(hwnd_map))

    used_hwnds: set = set()
    repositioned  = 0

    for win in windows:
        pname = win.get("process", "").lower()
        if not pname or _should_skip(pname):
            continue

        candidates = hwnd_map.get(pname, [])
        if not candidates:
            log.warning("[RESTORE] No hwnd for process '%s' — skipped", pname)
            continue

        saved_title = win.get("title", "").lower()[:40]

        # Pass 1: prefer a candidate whose title contains our 40-char prefix
        hwnd = 0
        if saved_title:
            for c in candidates:
                if c["hwnd"] not in used_hwnds and saved_title in c["title"]:
                    hwnd = c["hwnd"]
                    break

        # Pass 2: take any unused candidate for this process
        if not hwnd:
            for c in candidates:
                if c["hwnd"] not in used_hwnds:
                    hwnd = c["hwnd"]
                    break

        if hwnd:
            used_hwnds.add(hwnd)
            reposition(hwnd, win.get("pos", {}), win.get("show_cmd", 1))
            repositioned += 1
            log.info("[RESTORE] ✓ %s '%s' → hwnd %s", pname,
                     win.get("title", "")[:60], hwnd)
        else:
            log.warning("[RESTORE] All hwnds for '%s' already used — skipped", pname)

    log.info("[RESTORE] Complete. %d/%d windows repositioned.", repositioned, len(windows))


# ── Auto-Capture (Disabled) ───────────────────────────────────────────────────
def start_auto_capture(interval_seconds: int = 300):
    """
    DEPRECATED — auto-capture is disabled. Capture is now manual only,
    triggered by hardware button (CAPTURE command). This function is a
    no-op kept for backward compatibility.
    """
    log.info("[AUTO-CAPTURE] Disabled — use manual CAPTURE command instead.")


# ── Utilities ─────────────────────────────────────────────────────────────────
def open_recycle_bin():
    subprocess.Popen(
        ["explorer.exe", "shell:RecycleBinFolder"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
