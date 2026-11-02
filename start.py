"""
Deep Work AI — Start (v2)
=========================
Run: python start.py
Starts the TCP service as a hidden subprocess. The service itself runs the
activity recorder, workflow intelligence, Blocker Radar, Git Pulse and the
Debug watcher, so they work the same when the plugin auto-starts it.
"""

import logging
import signal
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Load .env before anything else
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass  # python-dotenv optional — read .env manually in feature modules

LOG_FILE = DATA_DIR / "deepworkai.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("start")

sys.path.insert(0, str(BASE_DIR))
from deepworkai.service.proc_utils import popen_hidden, get_python

_processes: dict = {}


def start():
    python = get_python()
    log.info("=" * 60)
    log.info("Deep Work AI v2 starting")
    log.info("Python: %s", python)

    # ── Subprocess services ────────────────────────────────────────────
    scripts = [
        ("Service",          BASE_DIR / "deepworkai" / "service"  / "deepwork_service.py"),
    ]
    for name, script in scripts:
        if not script.exists():
            log.error("Missing script: %s", script)
            continue
        proc = popen_hidden([python, str(script)], cwd=str(BASE_DIR))
        _processes[name] = proc
        log.info("%s started (PID %d)", name, proc.pid)

    # ── Ensure lcd_state.json exists ──────────────────────────────────
    try:
        from deepworkai.service.lcd_state import _write
        _write()
        log.info("LCD state initialised")
    except Exception as e:
        log.warning("LCD state init error: %s", e)

    log.info("All systems running. Ctrl+C to stop. Log: %s", LOG_FILE)

    def shutdown(sig, frame):
        log.info("Shutting down…")
        for name, proc in _processes.items():
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            log.info("Stopped %s", name)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT,  shutdown)

    # Health-check loop
    while True:
        time.sleep(30)
        for name, proc in _processes.items():
            if proc.poll() is not None:
                log.warning(
                    "%s stopped unexpectedly (exit %d) — check %s",
                    name, proc.returncode, LOG_FILE
                )


if __name__ == "__main__":
    start()
