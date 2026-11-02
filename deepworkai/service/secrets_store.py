"""
Secrets vault — API tokens encrypted at rest, never in plain text.

On Windows, secrets are encrypted with DPAPI (CryptProtectData, current-user
scope): only your Windows account on this PC can decrypt them. A copied file
is useless on another machine or account. The vault lives in data/secrets.bin.

Lookup order for get(): environment variable → vault → legacy .env file.

  python -m deepworkai.service.secrets_store import-env   # move tokens out of .env into the vault
  python -m deepworkai.service.secrets_store set SLACK_TOKEN
  python -m deepworkai.service.secrets_store list          # names only, never values
  python -m deepworkai.service.secrets_store delete SLACK_TOKEN
"""

from __future__ import annotations

import ctypes
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
VAULT = ROOT / "data" / "secrets.bin"
ENV_FILE = ROOT / ".env"
SECRET_KEYS = ("SLACK_TOKEN", "GITHUB_TOKEN", "JIRA_TOKEN")          # moved into the vault
_ENTROPY = b"DeepWorkAI.v1"
_cache: dict | None = None


# ── DPAPI (Windows) ───────────────────────────────────────────────────────────
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    src, ent, out = _blob(data), _blob(_ENTROPY), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out))  # UI_FORBIDDEN
    if not ok:
        raise OSError("DPAPI failed — the vault belongs to a different Windows user or PC")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def available() -> bool:
    return os.name == "nt"


def _restrict(path: Path):
    try:
        os.chmod(path, 0o600)
        if os.name == "nt":
            import subprocess
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{getpass.getuser()}:F"],
                           capture_output=True, timeout=5, creationflags=0x08000000)
    except Exception:
        pass


# ── Vault ─────────────────────────────────────────────────────────────────────
def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    _cache = {}
    if available() and VAULT.exists():
        try:
            _cache = json.loads(_dpapi(VAULT.read_bytes(), protect=False).decode())
        except Exception:
            _cache = {}
    return _cache


def _save(data: dict):
    global _cache
    if not available():
        raise RuntimeError("The encrypted vault needs Windows (DPAPI). Use environment variables instead.")
    VAULT.parent.mkdir(parents=True, exist_ok=True)
    tmp = VAULT.with_suffix(".tmp")
    tmp.write_bytes(_dpapi(json.dumps(data).encode(), protect=True))
    _restrict(tmp)
    tmp.replace(VAULT)
    _cache = dict(data)


def _env_file() -> dict:
    out: dict = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get(key: str, default: str = "") -> str:
    """Environment → encrypted vault → legacy .env (non-secret settings like GITHUB_REPO)."""
    return os.environ.get(key) or _load().get(key) or _env_file().get(key) or default


def set_secret(key: str, value: str):
    data = dict(_load())
    data[key] = value
    _save(data)


def delete(key: str):
    data = dict(_load())
    data.pop(key, None)
    _save(data)


def import_env() -> list[str]:
    """Move secret tokens from .env into the vault and blank them in .env."""
    env = _env_file()
    moved = [k for k in SECRET_KEYS if env.get(k)]
    if not moved:
        return []
    data = dict(_load())
    for k in moved:
        data[k] = env[k]
    _save(data)
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        k = line.split("=", 1)[0].strip()
        out.append(f"{k}=  # stored encrypted in data/secrets.bin" if k in moved and "=" in line
                   and not line.lstrip().startswith("#") else line)
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    return moved


def plaintext_secrets_in_env() -> list[str]:
    """Names of secret tokens still sitting in plain text in .env."""
    env = _env_file()
    return [k for k in SECRET_KEYS if env.get(k) and not env[k].startswith("#")]


def _main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 1
    cmd = argv[0]
    if cmd == "import-env":
        moved = import_env()
        print("Moved to the encrypted vault: " + ", ".join(moved) if moved else "No tokens found in .env")
    elif cmd == "set" and len(argv) == 2:
        set_secret(argv[1], getpass.getpass(f"{argv[1]} (input hidden): ").strip())
        print("Saved (encrypted).")
    elif cmd == "delete" and len(argv) == 2:
        delete(argv[1]); print("Deleted.")
    elif cmd == "list":
        print("\n".join(sorted(_load())) or "(vault is empty)")
    else:
        print(__doc__); return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
