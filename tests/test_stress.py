"""Stress and performance tests — the UX must not degrade under load."""
import json
import random
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from conftest import send


def auth(svc, cmd):
    return f"@{svc._SESSION_KEY} {cmd}"


def test_tcp_burst_200_clients(svc, server):
    """200 concurrent mixed clients: every one gets an answer, p95 stays snappy."""
    cmds = ["PING", auth(svc, "JOURNAL_GET"), auth(svc, "QUEUE_LIST"), "garbage",
            auth(svc, "WORKFLOW_STATUS"), "@bad JOURNAL_GET"]
    lat = []

    def one(i):
        t = time.perf_counter()
        r = send(server, cmds[i % len(cmds)])
        lat.append(time.perf_counter() - t)
        return r

    with ThreadPoolExecutor(max_workers=24) as ex:
        results = list(ex.map(one, range(200)))
    assert all(results), "a client got no response"
    lat.sort()
    assert lat[int(len(lat) * 0.95)] < 0.5, f"p95 {lat[int(len(lat)*0.95)]*1000:.0f} ms"


def test_dial_storm_keeps_state_consistent(svc, server):
    """Hundreds of interleaved dial ticks from many threads never corrupt Time Travel."""
    svc._handle_travel_close()
    n = len(svc.core.get_recent_snapshots(svc.TRAVEL_SPAN))

    def spin(i):
        return send(server, auth(svc, f"DIAL:{random.choice([-3, -1, 1, 2])}"))

    with ThreadPoolExecutor(max_workers=16) as ex:
        out = list(ex.map(spin, range(300)))
    assert all(r.startswith("OK DIAL travel") for r in out)
    st = json.loads(svc.TRAVEL_FILE.read_text())
    assert -1 <= st["index"] < n and st["open"]
    before = len(svc.core.restored)
    r = send(server, auth(svc, "TRAVEL_COMMIT"))
    assert r.startswith("OK TRAVEL")
    time.sleep(0.2)
    assert len(svc.core.restored) - before == (1 if "restored" in r else 0)
    assert send(server, auth(svc, "TRAVEL_COMMIT")) == "OK TRAVEL idle"   # double commit is a no-op


def test_travel_go_rejects_unknown_id(svc, server):
    assert send(server, auth(svc, "TRAVEL_GO:nope")).startswith("ERROR")


def test_workflow_inference_is_fast_on_big_windows():
    from deepworkai.features import workflow_intelligence as wi
    now = datetime.now()
    apps = ["VS Code", "Terminal", "Chrome", "Slack"]
    ev = [{"timestamp": (now - timedelta(seconds=5 * i)).isoformat(), "event_type": "app_switch",
           "app": apps[i % 4], "description": "x", "details": {"title": f"file{i}.py - repo"}}
          for i in range(5000)][::-1]
    t = time.perf_counter()
    st = wi.infer_state(ev, now=now)
    assert time.perf_counter() - t < 0.5
    assert 0 <= st.focus_score <= 100


def test_concurrent_notification_routing(tmp_path, monkeypatch):
    """Many threads writing decisions at once: no 'database is locked', nothing lost."""
    from deepworkai.features import workflow_intelligence as wi
    monkeypatch.setattr(wi, "INTEL_DB", tmp_path / "i.db")
    st = wi.WorkflowState(activity="coding", focus_score=85, deep=True)
    errors = []

    def route(i):
        try:
            wi.route_notification({"id": str(i), "priority": random.choice(["HIGH", "MEDIUM", "LOW"]),
                                   "confidence": 0.8, "sender": f"s{i % 7}"}, state=st)
            if i % 5 == 0:
                wi.record_feedback(f"s{i % 7}", opened=bool(i % 2))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=route, args=(i,)) for i in range(300)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert not errors
    import sqlite3
    with sqlite3.connect(wi.INTEL_DB) as c:
        assert c.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 300


def test_session_parser_fuzz_and_speed():
    from deepworkai.service import chromium_session as cs

    def rec(cmd, payload):
        return struct.pack("<HB", len(payload) + 1, cmd) + payload

    def nav(tid, idx, url):
        u = url.encode()
        body = struct.pack("<ii", tid, idx) + struct.pack("<i", len(u)) + u + b"\0" * (-len(u) % 4)
        return rec(cs.CMD_UPDATE_TAB_NAVIGATION, struct.pack("<I", len(body)) + body)

    big = b"SNSS" + struct.pack("<i", 3) + b"".join(
        nav(i % 300, i // 300, f"https://example.com/{i}") for i in range(50000))
    t = time.perf_counter()
    tabs = cs.parse_session(big)
    assert time.perf_counter() - t < 2.0 and len(tabs) == 300
    rnd = random.Random(1)
    for _ in range(2000):                         # random corruption must never raise
        b = bytearray(big[:4000])
        for _ in range(20):
            b[rnd.randrange(len(b))] = rnd.randrange(256)
        cs.parse_session(bytes(b))
    cs.parse_session(b"SNSS" + bytes(rnd.randrange(256) for _ in range(5000)))


def test_redaction_throughput():
    from deepworkai.features.workflow_intelligence import redact
    s = "mail a@b.com token=abc https://x.io/a?b=c " * 5
    t = time.perf_counter()
    for _ in range(10000):
        redact(s)
    assert time.perf_counter() - t < 2.0
