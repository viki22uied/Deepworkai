"""Security regression tests."""
import os
import socket
import time

from conftest import send


def auth(svc, cmd):
    return f"@{svc._SESSION_KEY} {cmd}"


# ── Local TCP auth ────────────────────────────────────────────────────────────
def test_ping_needs_no_key(server):
    assert "PONG" in send(server, "PING")


def test_commands_require_session_key(svc, server):
    assert send(server, "SHIELD_TOGGLE") == "ERROR AUTH"
    assert send(server, "@wrongkey SHIELD_TOGGLE") == "ERROR AUTH"
    assert send(server, "@ SHIELD_TOGGLE") == "ERROR AUTH"
    assert send(server, auth(svc, "JOURNAL_GET")).startswith("OK")


def test_key_file_is_private(svc):
    assert svc.KEY_FILE.read_text().strip() == svc._SESSION_KEY
    if os.name != "nt":
        assert oct(svc.KEY_FILE.stat().st_mode & 0o777) == "0o600"


def test_http_request_is_rejected(server):
    # A web page POSTing to localhost gets an HTTP request line, never a command.
    assert send(server, "POST / HTTP/1.1") == "ERROR AUTH"


def test_slow_client_cannot_hog_a_slot(server):
    s = socket.create_connection(("127.0.0.1", server))
    s.sendall(b"PIN")                                # never finishes the line
    t = time.time()
    s.settimeout(5)
    assert s.recv(10) == b""                         # server drops it
    assert time.time() - t < 4
    s.close()


def test_oversized_and_garbage_input(svc, server):
    assert send(server, auth(svc, "A" * 10000)).startswith("ERROR")
    assert send(server, auth(svc, "\x00\xff\x13")).startswith("ERROR")
    assert send(server, auth(svc, "REWIND:1;rm -rf /")).startswith("ERROR")
    assert send(server, auth(svc, "UNKNOWN_CMD")).startswith("ERROR")


# ── UI: no HTML injection, no dangerous URLs ──────────────────────────────────
def test_open_url_only_allows_web(monkeypatch):
    from deepworkai.ui import hub
    opened = []
    monkeypatch.setattr(hub.webbrowser, "open", opened.append)
    for bad in ("file:///C:/Windows/System32/calc.exe", "C:\\evil.exe", "javascript:alert(1)",
                "\\\\server\\share\\x.exe", "ms-settings:", "", "http://", "slack://open"):
        hub.open_url(bad)
    assert opened == []
    hub.open_url("https://github.com/acme/api/pull/1")
    assert opened == ["https://github.com/acme/api/pull/1"]


def test_labels_render_plain_text(qapp):
    from PyQt6.QtCore import Qt
    from deepworkai.ui import hub
    l = hub.label('<img src="file:///etc/passwd"><b>x</b>')
    assert l.textFormat() == Qt.TextFormat.PlainText


# ── IDE CLI / PowerShell injection guards ─────────────────────────────────────
def test_cmd_metacharacters_blocked():
    from deepworkai.service.ide_context import safe_cli_arg
    assert safe_cli_arg(r"D:\work\api\main.py")
    for bad in ("a&calc.exe", "a|b", "a>b", "%PATH%", 'a"b', "x^y", "a\nb", ""):
        assert not safe_cli_arg(bad)


def test_restore_anchor_refuses_unsafe_path(tmp_path, monkeypatch):
    import json
    from deepworkai.features import context_anchor as ca
    f = tmp_path / "anchor.json"
    f.write_text(json.dumps({"file": r"C:\x&calc.exe", "line": 1}))
    monkeypatch.setattr(ca, "ANCHOR_FILE", f)
    assert "unsafe" in ca.restore_anchor()


def test_redaction_scrubs_secrets():
    from deepworkai.features.workflow_intelligence import redact
    s = redact("ping bob@corp.com xoxb-123456789012-abcdefghij token: hunter2 "
               "https://x.io/cb?code=SECRET AKIAABCDEFGHIJKLMNOP 4111111111111111")
    for leak in ("bob@corp.com", "xoxb-", "hunter2", "SECRET", "AKIA", "4111111111111111"):
        assert leak not in s


# ── Secrets & data at rest ────────────────────────────────────────────────────
def test_secret_url_params_are_stripped():
    from deepworkai.service.chromium_session import strip_secret_params as s
    assert s("https://app.io/reset?token=abc&lang=en") == "https://app.io/reset?lang=en"
    assert s("https://app.io/cb?code=XYZ&state=123") == "https://app.io/cb"
    assert s("https://s3.aws.com/f?X-Amz-Signature=1&X-Amz-Credential=2") == "https://s3.aws.com/f"
    assert s("https://app.io/#access_token=SECRET") == "https://app.io/"
    assert s("https://github.com/acme/api/pull/1?tab=files") == "https://github.com/acme/api/pull/1?tab=files"


def test_vault_lookup_order(tmp_path, monkeypatch):
    from deepworkai.service import secrets_store as ss
    env = tmp_path / ".env"
    env.write_text("SLACK_TOKEN=xoxb-plain\nGITHUB_REPO=acme/api\n")
    monkeypatch.setattr(ss, "ENV_FILE", env)
    monkeypatch.setattr(ss, "_cache", {"GITHUB_TOKEN": "ghp_vault"})
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert ss.get("GITHUB_TOKEN") == "ghp_vault"
    assert ss.get("GITHUB_REPO") == "acme/api"
    assert ss.plaintext_secrets_in_env() == ["SLACK_TOKEN"]
    monkeypatch.setenv("GITHUB_TOKEN", "from_env")
    assert ss.get("GITHUB_TOKEN") == "from_env"


def test_logs_never_contain_message_content(svc, server, tmp_path):
    import logging
    from deepworkai.features import notification_classifier as nc
    records = []
    h = logging.Handler(); h.emit = records.append
    logging.getLogger().addHandler(h)
    try:
        nc.DB_PATH = tmp_path / "n.db"
        nc.inject_notification("slack", "salary review for jane doe", "confidential", sender="hr-bot")
        send_ = __import__("conftest").send
        send_(server, f"@{svc._SESSION_KEY} JOURNAL_SAVE:my private note")
    finally:
        logging.getLogger().removeHandler(h)
    text = " ".join(r.getMessage() for r in records)
    for leak in ("salary", "jane", "hr-bot", "private note"):
        assert leak not in text


def test_github_repo_and_branch_are_validated(monkeypatch):
    from deepworkai.features import blocker_radar as br
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: calls.append(req.full_url) or (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(br, "_cfg", lambda k: {"GITHUB_TOKEN": "t", "GITHUB_REPO": REPO[0]}.get(k, ""))
    monkeypatch.delenv("DEEPWORKAI_OFFLINE", raising=False)
    for bad in ("acme/../../user", "acme/api?x=1", "../orgs/x", "acme", "acme/api/extra"):
        REPO[0] = bad
        assert br._gh("pulls") is None
    assert calls == []                                   # no request was even attempted
    REPO[0] = "acme/api"
    br._ci_status("feat/x?#..")
    assert calls and calls[-1].endswith("/repos/acme/api/commits/feat%2Fx%3F%23../check-runs")


REPO = ["acme/api"]


def test_restore_logs_no_window_titles(monkeypatch, caplog):
    import logging
    import importlib.util  # the real module: conftest stubs deep_restore_core for service tests
    from conftest import ROOT
    spec = importlib.util.spec_from_file_location("drc_real", ROOT / "deepworkai" / "service" / "deep_restore_core.py")
    core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)
    monkeypatch.setattr(core, "enum_windows", lambda: [])
    monkeypatch.setattr(core, "_snapshot_hwnds", lambda: {"code.exe": [{"hwnd": 7, "title": "x"}]})
    monkeypatch.setattr(core, "reposition", lambda *a: None)
    with caplog.at_level(logging.DEBUG):
        core.restore_workspace({"windows": [{"process": "code.exe", "title": "secret-salary.xlsx - Code"}],
                                "browsers": {}, "tabs_format": core.TABS_FORMAT})
    assert "secret-salary" not in caplog.text
