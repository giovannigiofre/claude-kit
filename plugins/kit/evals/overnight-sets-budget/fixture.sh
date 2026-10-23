#!/bin/sh
# A tiny repo with a gate in kit.json: calc.py has an untested function with a bug.
set -e
git init -q -b main .
git config user.email eval@example.invalid
git config user.name eval
cat > calc.py <<'PY'
def add(a, b):
    return a + b


def sub(a, b):
    return a + b
PY
cat > test_calc.py <<'PY'
from calc import add


def test_add():
    assert add(2, 3) == 5
PY
mkdir -p .claude
printf '{"check": "python3 -m pytest -q", "verify": "python3 -m pytest -q"}\n' > .claude/kit.json
git add -A && git commit -qm "calc with a test for add"
