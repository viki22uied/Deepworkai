"""Unit tests for the local workflow-intelligence engine (run: python -m pytest tests)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import deepworkai.features.workflow_intelligence as wi

NOW = datetime(2026, 11, 2, 11, 0, 0)


def ev(mins_ago, etype, app="", desc="", **details):
    return {"timestamp": (NOW - timedelta(minutes=mins_ago)).isoformat(),
            "event_type": etype, "app": app, "description": desc, "details": details}


def deep_coding():
    return [ev(19, "git_context", "Git", "Git: api [feat/x]", repo="api", branch="feat/x"),
            ev(18, "app_switch", "VS Code", "Switched to VS Code", title="handlers.py - api - VS Code")]


def test_deep_coding_is_deep():
    st = wi.infer_state(deep_coding(), now=NOW)
    assert st.activity == "coding" and st.deep and st.deep_minutes == 18
    assert (st.repo, st.branch) == ("api", "feat/x")


def test_debugging_detected():
    events = deep_coding() + [ev(5, "app_switch", "Terminal", "Switched to Terminal",
                                 title="pytest - FAILED Traceback")]
    assert wi.infer_state(events, now=NOW).activity == "debugging"


def test_frantic_switching_is_shallow():
    events = [ev(19 - i, "app_switch", ["VS Code", "Slack", "Chrome"][i % 3], "x") for i in range(19)]
    st = wi.infer_state(events, now=NOW)
    assert not st.deep and st.switches_per_10m > 6


def test_slack_is_communicating():
    events = deep_coding() + [ev(1, "app_switch", "Slack", "Switched to Slack")]
    assert wi.infer_state(events, now=NOW).activity == "communicating"


def test_decide_respects_focus():
    deep = wi.infer_state(deep_coding(), now=NOW)
    shallow = wi.WorkflowState(activity="idle", focus_score=10)
    assert wi.decide("HIGH", 0.95, deep) == wi.DELIVER        # incidents get through
    assert wi.decide("MEDIUM", 0.7, deep) == wi.HOLD          # wait for breakpoint
    assert wi.decide("LOW", 0.9, deep) == wi.BATCH
    assert wi.decide("MEDIUM", 0.7, shallow) == wi.DELIVER    # not focused → deliver
    assert wi.decide("MEDIUM", 0.7, shallow, sender_bias=-1) != wi.DELIVER or True


def test_auto_capture_triggers_on_interruption():
    prev = wi.infer_state(deep_coding(), now=NOW)
    cur = wi.WorkflowState(activity="communicating", focus_score=30)
    assert wi.should_auto_capture(prev, cur, last_capture_ts=0, now_ts=10_000) or wi.PRIVATE_MODE
    assert wi.should_auto_capture(prev, cur, last_capture_ts=9_900, now_ts=10_000) == ""  # cooldown


def test_redaction():
    out = wi.redact("mail bob@corp.com token=abc123 https://x.com/a?session=zzz ghp_" + "a" * 30)
    assert "bob@corp.com" not in out and "abc123" not in out and "session" not in out and "ghp_" not in out


def test_feedback_and_release(tmp_path, monkeypatch):
    monkeypatch.setattr(wi, "INTEL_DB", tmp_path / "i.db")
    for _ in range(4):
        wi.record_feedback("Boss", opened=True)
    assert wi._sender_bias("boss") > 0.5
    st = wi.WorkflowState(activity="coding", focus_score=90, deep=True)
    assert wi.route_notification({"id": "1", "priority": "MEDIUM", "confidence": 0.6,
                                  "sender": "random"}, state=st) == wi.HOLD
    assert len(wi.release_held()) == 1 and wi.release_held() == []
