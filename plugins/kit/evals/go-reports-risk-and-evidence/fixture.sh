#!/bin/sh
# A tiny CLI on a feature branch: --upper was just added, with a unit test that never runs the CLI.
set -e
git init -q -b main .
git config user.email eval@example.invalid
git config user.name eval
cat > greet.py <<'PY'
import sys


def greet(name):
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(greet(sys.argv[1] if len(sys.argv) > 1 else "world"))
PY
git add -A && git commit -qm "greet CLI"
git checkout -q -b feat/upper
cat > greet.py <<'PY'
import sys


def greet(name, upper=False):
    text = f"Hello, {name}!"
    return text.upper() if upper else text


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--upper"]
    print(greet(args[0] if args else "world", upper="--upper" in sys.argv))
PY
cat > test_greet.py <<'PY'
from greet import greet


def test_upper():
    assert greet("ada", upper=True) == "HELLO, ADA!"
PY
mkdir -p .claude
printf '{"check": "python3 -m pytest -q", "verify": "python3 -m pytest -q"}\n' > .claude/kit.json
