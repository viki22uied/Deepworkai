"""
Deep Work AI — entry point of the packaged app (DeepWorkAI.exe).

  DeepWorkAI.exe                 → background service (started by the Logitech plugin)
  DeepWorkAI.exe --hub [args]    → the Hub window (started by the service)
  DeepWorkAI.exe --secrets ...   → manage the encrypted token vault
"""
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):            # running from source
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--hub":
        from deepworkai.ui.hub import main as hub_main
        return hub_main(args[1:]) or 0
    if args and args[0] == "--secrets":
        from deepworkai.service.secrets_store import _main
        return _main(args[1:])
    sys.path.insert(0, str(Path(__file__).resolve().parent / "service"))
    from deepworkai.service.deepwork_service import main as service_main
    service_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
