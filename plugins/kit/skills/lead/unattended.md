# Before an unattended run

A run is unattended when the user says they are leaving (an evening, a night, "act on your
own"), or starts an overnight; `I away on` is the switch. Until they are back nobody
answers a permission prompt, and a thread or you waiting on one waits for hours. They are back
when they write: at the user's next message after `away on`, run `I away off` before anything else.
Only you run `away`, `sandbox` and `unattended` with arguments; a thread's attempt is denied.

1. **While the user can still answer**, do every pending merge, rebase and push: yours, and
   those of threads that handed back unpushed. Nothing that needs them should be left for the night.
2. **Read this repo's git preferences**: `I unattended`. It prints the brief line `UNATTENDED:
   push=<ask|allow> rebase=<ask|allow> merge=<ask|allow>`. Not set, they are the defaults: push
   and rebase allowed (on the thread's own branch), merge asked, so the user merges. Do not ask
   about them; when the user says otherwise about push or rebase, save it (`I unattended push=ask`)
   into this repo's gitignored `.claude/kit.local.json`: never global, never committed. merge=allow
   is the user's to set: `I unattended merge=allow` is refused and says where he writes it.
3. **The printed line is the effective value.** An `allow` stays `ask` while a deny or ask rule
   in any scope matches the step (managed settings, `~/.claude/settings.json`, the repo's
   `.claude/settings.json` or `settings.local.json`), since Claude Code checks those before allow,
   or while no allow rule covers it; the note under the line names the rule and the file. Brief
   the line exactly as printed and tell the user that note in one line; change nothing. Only when
   the user asks how to change the rules, run `I unattended --proposal`: it prints the diff per
   file and applies nothing. Apply it only when they ask you to, with AskUserQuestion (the
   question naming the file and the change, a committed file reaching every contributor; the diff
   in an option's `preview`; options «Applica la modifica ai settings» and «Non applicare»), then
   an ordinary Edit per file, which the kit's hook turns into Claude Code's own Yes/No prompt.
   Never edit settings unasked; a thread's edit is refused.
4. **Brief every thread of the run with the `UNATTENDED:` line**, and SendMessage it to threads
   already working. A thread does not run a step set to `ask`: it commits and hands back `needs
   push` (or rebase, merge). The same holds for your own commands. Put what waits under NEEDS
   YOU, for when the user is back.
