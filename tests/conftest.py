"""
Shared test setup. The service imports Windows-only modules (winreg, pywin32 via
deep_restore_core); those are stubbed so the *real* service logic — command
routing, auth, time travel, the TCP server — can be exercised on any OS.
"""
import os
import socket
import sys
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deepworkai" / "service"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

os.environ["DEEPWORKAI_OFFLINE"] = "1"          # tests never call GitHub/Slack/Jira
os.environ.pop("DEEPWORKAI_BLOCK_DISTRACTIONS", None)

# Tests must never act on the PC running them. A missed fake once made the suite open
# VS Code for real; now any attempt to start a program, open a page or press keys fails
# the test instead. Only read-only helpers the code needs are allowed.
_ALLOWED_EXES = {"git", "icacls", "where"}


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    import subprocess
    import webbrowser
    real_popen = subprocess.Popen

    def guarded(args, *a, **k):
        exe = Path(str(args[0] if isinstance(args, (list, tuple)) else str(args).split()[0])).stem.lower()
        if exe not in _ALLOWED_EXES:
            raise AssertionError(f"test tried to start a real program: {exe}")
        return real_popen(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", guarded)
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("test opened a browser")))
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", lambda *a, **k: (_ for _ in ()).throw(AssertionError("test opened a file")))
    fake = types.ModuleType("pyautogui")              # stand-in: the real one would press keys
    for f in ("press", "hotkey", "typewrite", "write", "click"):
        setattr(fake, f, lambda *a, **k: (_ for _ in ()).throw(AssertionError("test pressed keys")))
    monkeypatch.setitem(sys.modules, "pyautogui", fake)



class FakeCore(types.ModuleType):
    """Stands in for deep_restore_core (pywin32/winreg) only."""
    def __init__(self):
        super().__init__("deep_restore_core")
        self.snapshots = [{"id": f"id{i}", "timestamp": "", "summary": ""} for i in range(5)]
        self.restored: list = []
        self.captured = 0

    def init_db(self): pass
    def get_recent_snapshots(self, limit=10): return self.snapshots[:limit]
    def load_snapshot_by_id(self, cid): return ({"x": 1}, cid, "summary") if cid.startswith("id") else (None, "", "")
    def load_latest_snapshot(self): return ({"x": 1}, "latest", "summary")
    def load_snapshot_before(self, m): return ({"x": 1}, f"before{m}", "summary")
    def restore_workspace(self, snap, ts, travel=False): self.restored.append(ts)
    def capture_workspace(self): return {"windows": [], "browsers": {}}
    def save_snapshot(self, snap, name, context=None):
        self.captured += 1
        return f"cap{self.captured:08d}"
    def prune_auto_snapshots(self, days=14): pass


@pytest.fixture(scope="session")
def svc(tmp_path_factory):
    core = FakeCore()
    sys.modules["deep_restore_core"] = core
    sys.modules.setdefault("slack_integration", types.ModuleType("slack_integration"))
    import ctypes
    if not hasattr(ctypes, "windll"):
        ctypes.windll = None
    import deepwork_service as service
    service.core = core
    service._ui_ensure = lambda: None            # don't spawn a GUI from tests
    service._init_session_key()
    return service


@pytest.fixture(scope="session")
def server(svc):
    """The real accept loop on an ephemeral port."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(64)
    threading.Thread(target=svc.serve_forever, args=(srv,), daemon=True).start()
    yield srv.getsockname()[1]
    srv.close()


def send(port: int, line: str, timeout: float = 5.0) -> str:
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall((line + "\n").encode())
        return s.recv(4096).decode(errors="ignore").strip()


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
