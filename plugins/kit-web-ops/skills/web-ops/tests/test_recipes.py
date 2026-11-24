#!/usr/bin/env python3
"""Runs the API-key recipe of google.md, as written, against fake gcloud and gh commands: the key
gcloud prints on stderr must not reach the caller, and no curl recipe may carry a secret in argv."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
KEY = "AIzaFAKEfakeFAKEfakeFAKEfakeFAKE0000001"
GCLOUD = r"""#!/bin/sh
case "$*" in
*"api-keys create"*)
  printf 'Operation [op] complete. Result: {\n    "keyString":"%s"\n}\n' "$KEY" >&2
  [ "$MODE" = create ] && { echo "ERROR: (gcloud) boom $KEY" >&2; exit 1; }
  [ "$MODE" = signal ] && kill -TERM "$PPID"
  echo "{\"response\":{\"keyString\":\"$KEY\"}}" ;;
*get-key-string*)
  echo "warning $KEY" >&2
  [ "$MODE" = get ] && { echo "ERROR: (gcloud) denied $KEY" >&2; exit 1; }
  [ "$MODE" = empty ] || echo "$KEY" ;;
esac
exit 0
"""
GH = '#!/bin/sh\ncat > "$STORE"\n[ "$MODE" = gh ] && exit 1\nexit 0\n'


def bash_blocks(name):
    return re.findall(r"```bash\n(.*?)```", (SKILL / name).read_text(), re.S)


def recipe():
    block, = [b for b in bash_blocks("google.md") if "api-keys create" in b]
    return block.replace("<site>", "site").replace("<id>", "proj")


class ApiKeyRecipe(unittest.TestCase):
    def run_recipe(self, shell, mode):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "bin").mkdir()
            (root / "tmp").mkdir()
            for name, body in (("gcloud", GCLOUD), ("gh", GH)):
                (root / "bin" / name).write_text(body)
                (root / "bin" / name).chmod(0o755)
            # mktemp -d ignores TMPDIR on macOS, so the fake makes the folder where we can see it
            (root / "bin" / "mktemp").write_text('#!/bin/sh\nmkdir "$SEEN/d" && echo "$SEEN/d"\n')
            (root / "bin" / "mktemp").chmod(0o755)
            env = {"PATH": f"{root / 'bin'}:{os.environ['PATH']}", "HOME": d, "KEY": KEY, "MODE": mode,
                   "STORE": str(root / "store"), "SEEN": str(root / "tmp")}
            out = subprocess.run([shell, "-c", recipe()], env=env, capture_output=True, text=True, timeout=30)
            store = (root / "store").read_text().strip() if (root / "store").exists() else None
            return out.returncode, out.stdout + out.stderr, store, list((root / "tmp").iterdir())

    def test_no_key_in_output_and_no_file_left(self):
        for shell in filter(shutil.which, ("bash", "zsh")):
            for mode in ("ok", "create", "get", "empty", "gh", "signal"):
                with self.subTest(shell=shell, mode=mode):
                    code, out, store, left = self.run_recipe(shell, mode)
                    self.assertNotIn(KEY, out)
                    self.assertEqual(left, [])
                    self.assertEqual(code == 0, mode == "ok", out)
                    self.assertEqual(store, KEY if mode in ("ok", "gh") else None)


class CurlRecipes(unittest.TestCase):
    def test_no_secret_in_curl_arguments(self):
        for path in SKILL.glob("*.md"):
            for command in re.findall(r"\bcurl\b[^|`]*", path.read_text()):
                self.assertNotRegex(command, r"\$\w*(?:TOKEN|KEY|SECRET)|\$\(gcloud", path.name)


if __name__ == "__main__":
    unittest.main()
