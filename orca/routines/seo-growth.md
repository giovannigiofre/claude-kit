ROUTINE: seo-growth run for @SITE@ (the owner's standing routine). Nobody is watching. Your only job is one run of the `seo-growth` agent; start no other work and do not route this to kit:lead.

You are in a fresh worktree Orca made for this run, on its own branch. Make sure it is at origin/main with nothing uncommitted; if not, stop and say so.

1. `git -C ~/.local/share/claude-kit/main fetch -q origin && git -C ~/.local/share/claude-kit/main checkout -q --detach origin/main`
2. Start the `seo-growth` agent in the foreground with this brief:
   PROJECT: @SITE@
   WORKTREE: this directory (absolute path)
   AGENT_DIR: the absolute path of ~/.local/share/claude-kit/main/omnigent/agents/seo-growth
   SEO_GROWTH_HOME: the absolute path of ~/.local/share/claude-kit/seo-growth, exported for every script
   SHIP: pr
   Wait for its report in this turn; never sleep or poll.
3. No PR opened: your final message is its first line and its WHY line, nothing else.
4. A PR opened: run `kit:verifier` on it against the seo-growth rules (an official source for every figure, no scaled pages, only the stated change, DE/FR/IT copy flagged for the owner). Final message, in Italian: the PR link, the one-line intent, the verdict.
Never merge, whatever kit.json lead.merge says: the owner merges seo-growth PRs.
