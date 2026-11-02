"""
Single source of truth for where Deep Work AI keeps its data.

  1. DEEPWORKAI_DATA environment variable (tests, custom setups)
  2. Installed app (frozen .exe):  %LOCALAPPDATA%\\DeepWorkAI\\data
     — outside the plugin folder, which Logi Options+ replaces on every update
  3. Running from source:          <repo>/data
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # repo root (source runs)
FROZEN = bool(getattr(sys, "frozen", False))


def _app_home() -> Path:
    if os.environ.get("DEEPWORKAI_HOME"):
        return Path(os.environ["DEEPWORKAI_HOME"])
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "DeepWorkAI"
    return PROJECT_ROOT


APP_HOME = _app_home()                       # holds data/ and the optional .env
DATA_DIR = Path(os.environ["DEEPWORKAI_DATA"]) if os.environ.get("DEEPWORKAI_DATA") else APP_HOME / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = APP_HOME / ".env"

# Databases
ACTIVITY_DB = DATA_DIR / "activity.db"
SNAPSHOTS_DB = DATA_DIR / "capsules.db"  # workspace snapshots
QUEUE_DB = DATA_DIR / "queue.db"

# Files
JOURNAL_FILE = DATA_DIR / "next_step.txt"
