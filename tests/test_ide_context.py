"""Real-data plumbing: which project/file you're in."""
import json

from deepworkai.service import ide_context as ic


def test_parse_title_variants():
    assert ic.parse_title("● app.py - my-repo - Visual Studio Code") == ("app.py", "my-repo")
    assert ic.parse_title("app.py — my-repo — Cursor") == ("app.py", "my-repo")
    assert ic.parse_title("README.md - docs (Workspace) - Visual Studio Code") == ("README.md", "docs")
    assert ic.parse_title("my-repo - Visual Studio Code") == ("", "my-repo")
    assert ic.parse_title("") == ("", "")


def test_uri_to_path_decodes_windows_drive():
    assert ic.uri_to_path("file:///d%3A/work/api") == "d:/work/api"
    assert ic.uri_to_path("file:///home/me/my%20repo") == "/home/me/my repo"


def test_active_workspace_matches_title(tmp_path, monkeypatch):
    a, b = tmp_path / "api", tmp_path / "web"
    a.mkdir(); b.mkdir()
    store = tmp_path / "storage.json"
    store.write_text(json.dumps({"windowsState": {
        "lastActiveWindow": {"folder": a.as_uri()},
        "openedWindows": [{"folder": b.as_uri()}]}}))
    monkeypatch.setattr(ic, "_storage_files", lambda: [store])
    ic._cache["t"] = 0
    assert ic.active_workspace("x.ts - web - Visual Studio Code") == str(b)
    assert ic.active_workspace("") == str(a)
