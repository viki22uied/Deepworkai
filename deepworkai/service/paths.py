from pathlib import Path

# Single source of truth for all shared Deep Work AI data paths.
# All services and overlays must import from here (no local Path(__file__) chains).
PROJECT_ROOT = Path(__file__).parent.parent.parent  # repo root
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Databases
ACTIVITY_DB = DATA_DIR / "activity.db"
SNAPSHOTS_DB = DATA_DIR / "capsules.db"  # workspace snapshots
QUEUE_DB = DATA_DIR / "queue.db"

# Files
JOURNAL_FILE = DATA_DIR / "next_step.txt"
