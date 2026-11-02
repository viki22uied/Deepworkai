"""
Terminal Command Palette
========================
6 developer-defined commands, each mapped to an LCD button slot.
Pressing a button runs the command in a new Windows Terminal tab.
Commands are configured in data/palette.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BASE_DIR     = Path(__file__).parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from deepworkai.service.paths import DATA_DIR  # one data folder (installed app or repo)
DATA_DIR.mkdir(parents=True, exist_ok=True)
PALETTE_FILE = DATA_DIR / "palette.json"

DEFAULT_PALETTE = [
    {"label": "Tests",  "cmd": "npm test"},
    {"label": "Dev",    "cmd": "npm run dev"},
    {"label": "Build",  "cmd": "docker compose up --build"},
    {"label": "Push",   "cmd": "git push"},
    {"label": "Pull",   "cmd": "git pull --rebase"},
    {"label": "Logs",   "cmd": "docker compose logs -f"},
]


def load_palette() -> list[dict]:
    if not PALETTE_FILE.exists():
        save_palette(DEFAULT_PALETTE)
        return DEFAULT_PALETTE
    try:
        data = json.loads(PALETTE_FILE.read_text(encoding="utf-8"))
        # Pad to exactly 6
        while len(data) < 6:
            data.append({"label": f"Slot {len(data)+1}", "cmd": ""})
        return data[:6]
    except Exception:
        return DEFAULT_PALETTE


def save_palette(palette: list[dict]) -> str:
    while len(palette) < 6:
        palette.append({"label": f"Slot {len(palette)+1}", "cmd": ""})
    PALETTE_FILE.write_text(json.dumps(palette[:6], indent=2), encoding="utf-8")
    return "palette saved"


def get_palette_labels() -> list[str]:
    return [e.get("label", "?")[:8] for e in load_palette()]


def run_slot(slot_index: int) -> str:
    """Run command at slot_index (0-5) in a new Windows Terminal tab."""
    palette = load_palette()
    if not 0 <= slot_index < len(palette):
        return f"invalid slot: {slot_index}"

    entry = palette[slot_index]
    cmd   = entry.get("cmd", "").strip()
    label = entry.get("label", f"Slot{slot_index}")

    if not cmd:
        return f"slot {slot_index} ({label}) is empty — edit data/palette.json"

    try:
        if sys.platform == "win32":
            # Open in a new Windows Terminal tab (visible window — user needs to see output)
            subprocess.Popen(
                ["wt", "--window", "0", "new-tab",
                 "--title", label,
                 "powershell", "-NoExit", "-Command", cmd],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.Popen(["bash", "-c", f'osascript -e \'tell app "Terminal" to do script "{cmd}"\''])
        return f"▶ {label}: {cmd}"
    except FileNotFoundError:
        # wt.exe not found — fall back to plain PowerShell window
        try:
            subprocess.Popen(
                ["powershell", "-NoExit", "-Command", cmd],
                creationflags=0,   # visible window
            )
            return f"▶ {label} (powershell fallback)"
        except Exception as e2:
            return f"failed: {e2}"
    except Exception as e:
        return f"failed: {e}"
