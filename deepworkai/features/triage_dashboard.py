"""
Deep Work AI — Triage Dashboard (entry point kept for the TRIAGE_SHOW command).
The old tkinter window was replaced by the PyQt6 Hub in deepworkai/ui/hub.py.

  python triage_dashboard.py [--filter HIGH] [--demo] [--tab inbox|focus|insights]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from deepworkai.ui.hub import main  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--tab" not in args:
        args = ["--tab", "inbox"] + args
    sys.exit(main(args))
