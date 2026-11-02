"""
Smoke test for the packaged app: start DeepWorkAI.exe in a throwaway home folder,
then prove the service is up, authenticated commands work and the Hub launches.
Usage: python packaging/smoke_test.py path/to/DeepWorkAI.exe
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

exe = Path(sys.argv[1]).resolve()
try:                                   # a copy already running would answer instead of ours
    socket.create_connection(("127.0.0.1", 57321), timeout=0.5).close()
    raise SystemExit("FAIL: port 57321 is in use - quit the running Deep Work AI first")
except OSError:
    pass
home = Path(tempfile.mkdtemp(prefix="dwai-smoke-"))
env = dict(os.environ, DEEPWORKAI_HOME=str(home), DEEPWORKAI_OFFLINE="1", QT_QPA_PLATFORM="offscreen")
proc = subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent))
# Fast key presses on a fresh install can start several copies at once: only one may survive.
extras = [subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent)) for _ in range(3)]


def send(line: str) -> str:
    with socket.create_connection(("127.0.0.1", 57321), timeout=5) as s:
        s.sendall((line + "\n").encode())
        return s.recv(4096).decode(errors="ignore").strip()


try:
    deadline = time.time() + 60
    while True:
        try:
            if "PONG" in send("PING"):
                break
        except OSError:
            pass
        if all(p.poll() is not None for p in [proc] + extras):
            raise SystemExit(f"FAIL: app exited with code {proc.returncode}")
        if time.time() > deadline:
            raise SystemExit("FAIL: service did not answer within 60 s")
        time.sleep(1)
    print("ok  service answers PING")

    key_file = home / "data" / ".session_key"
    assert key_file.exists(), "session key not written to the app data folder"
    key = key_file.read_text().strip()
    print("ok  session key in", key_file.parent)

    assert send("JOURNAL_GET").startswith("ERROR AUTH"), "unauthenticated command was accepted"
    print("ok  unauthenticated command rejected")

    assert send(f"@{key} JOURNAL_SAVE:smoke test") == "OK JOURNAL_SAVE"
    assert "smoke test" in send(f"@{key} JOURNAL_GET")
    print("ok  authenticated round trip")

    for cmd in ("WORKFLOW_STATUS", "STATUS", "INSIGHTS", "HUB"):
        r = send(f"@{key} {cmd}")
        assert r.startswith("OK"), f"{cmd}: {r[:120]}"
    print("ok  core commands")

    launched = [proc] + extras              # any one of them may win the race
    deadline = time.time() + 10
    while sum(p.poll() is None for p in launched) > 1 and time.time() < deadline:
        time.sleep(0.2)
    assert sum(p.poll() is None for p in launched) == 1, "more than one copy kept running"
    import psutil
    mine = [p for p in psutil.process_iter(["exe"]) if (p.info["exe"] or "").lower() == str(exe).lower()]
    assert len(mine) <= 2, f"{len(mine)} copies running (expected service + Hub)"
    assert send(f"@{key} STATUS").startswith("OK"), "session key changed by a second copy"
    print(f"ok  4 simultaneous launches -> {len(mine)} processes (service + Hub)")
    log_text = (home / "data" / "service.log").read_text(errors="ignore")   # must stay readable
    assert "smoke test" not in log_text, "journal text leaked into service.log"
    print("ok  service.log readable, no private text")
    print("PASS")
finally:
    for p in [proc] + extras:
        p.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    if os.name == "nt":                              # the Hub runs as a child process
        subprocess.run(["taskkill", "/F", "/IM", exe.name], capture_output=True)
