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
