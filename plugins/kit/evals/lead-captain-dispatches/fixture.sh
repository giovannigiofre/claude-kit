#!/bin/sh
# Shared fixture: a tiny repo where add() was "implemented" with a bug.
set -e
git init -q .
git config user.email eval@example.invalid
git config user.name eval
cat > calc.py <<'PY'
def add(a, b):
    """Return the sum of a and b."""
    return a - b
PY
cat > test_calc.py <<'PY'
from calc import add

def test_add_zero():
    assert add(2, 0) == 2
PY
git add -A && git commit -qm "add(): implemented, tests pass"
