#!/bin/sh
# Precheck of a seo-growth run: removes earlier runs' worktrees that left nothing behind, then
# always exits 0 (the run goes ahead). A worktree is removed only when it is an Orca
# auto-seo-growth-* one, older than two hours, clean, and its HEAD is already on origin/main
# (a run that opened no PR, or whose PR merged). Anything else is kept.
cd "${1:-.}" || exit 0
O="${ORCA_CLI_COMMAND:-orca}"
git fetch -q origin 2>/dev/null || true
git worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' | while read -r p; do
  case "$(basename "$p")" in auto-seo-growth-*) ;; *) continue ;; esac
  [ -n "$(find "$p" -maxdepth 0 -mmin +120 2>/dev/null)" ] || continue
  [ -z "$(git -C "$p" status --porcelain 2>/dev/null)" ] || continue
  git -C "$p" merge-base --is-ancestor HEAD origin/main 2>/dev/null || continue
  "$O" worktree rm --worktree "path:$p" --delete-branch >/dev/null 2>&1 \
    && echo "removed $p" || echo "kept $p (orca worktree rm failed)"
done
exit 0
