# Before an unattended run

A run is unattended when the user says they are leaving (an evening, a night, "act on your
own"), turns on `/kit-safety unattended on`, or starts an overnight. Until they are back nobody
answers a permission prompt, and a thread or you waiting on one waits for hours.

1. **While the user can still answer**, do every pending merge, rebase and push: yours, and
   those of threads that handed back unpushed. Nothing that needs them should be left for the night.
2. **Read this repo's git preferences**: `I unattended`. It prints the brief line `UNATTENDED:
   push=<ask|allow> rebase=<ask|allow> merge=<ask|allow>`. When it says *not set*, ask the user
   once, in one question: during unattended runs in this repo, may threads and you push, rebase,
   merge without asking (`allow`), or should each wait for them (`ask`, the default)? Save the
   answer: `I unattended push=allow rebase=ask merge=ask`. It goes into this repo's gitignored
   `.claude/kit.local.json`: never global, never committed. Do not ask again in this repo; the
   user changes it by saying so.
3. **For a step set to `allow`**, the same command prints the permission rule it needs and the
   file it belongs in (the repo's `.claude/settings.local.json`, `permissions.allow`). Tell the
   user the exact rule and file; the user adds it. Never edit permission settings yourself. Until
   the rule is there (read the file to check), brief that step as `ask`.
4. **Brief every thread of the run with the `UNATTENDED:` line**, and SendMessage it to threads
   already working. A thread does not run a step set to `ask`: it commits and hands back `needs
   push` (or rebase, merge). The same holds for your own commands. Put what waits under NEEDS
   YOU, for when the user is back.
