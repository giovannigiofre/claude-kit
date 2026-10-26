#!/usr/bin/env python3
"""SessionEnd: once distill.EVENTS_TO_RUN lessons events are pending for this repo, run the
distiller (distill.py) in a detached process, so the session ends without waiting. Silent. A
project without .claude/kit.json does nothing. Standard library only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402


def main():
    data = kitlib.read_input()
    root = kitlib.project_root(data)
    config, _ = kitlib.load_config(root)
    if not config:
        return 0
    try:
        import distill
        if distill.pending(root) >= distill.EVENTS_TO_RUN:
            distill.spawn(root)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
