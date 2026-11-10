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
3. **For a step set to `allow`**, the command checks the permission rules in every scope, and the
   line it prints is the effective value. A saved `allow` stays `ask` while a deny or ask rule
   anywhere matches the step (managed settings, the user's `~/.claude/settings.json`, the repo's
   `.claude/settings.json` or `settings.local.json`). Claude Code checks deny and ask before
   allow, so an allow rule cannot override one: the user changes that rule. It also stays `ask`
   while no allow rule covers the step: the user adds the rule the note names to
   `.claude/settings.local.json`. Tell the user the exact rule and file, and brief the line
   exactly as the command prints it. The command also prints a PROPOSAL with a diff per file.
   Apply it only when the user asks you to: ask with AskUserQuestion, the question naming the
   file and the change (a committed file reaches every contributor), the diff in an option's
   `preview`, options «Applica la modifica ai settings» and «Non applicare». On «Applica» make an
   ordinary Edit per file; the kit's hook turns it into Claude Code's own Yes/No prompt headed
   «Sovrascrittura dei settings di Claude Code:». The user approves twice with buttons and types
   nothing, or edits the file by hand. Never edit settings unasked; a thread's edit is refused.
4. **Brief every thread of the run with the `UNATTENDED:` line**, and SendMessage it to threads
   already working. A thread does not run a step set to `ask`: it commits and hands back `needs
   push` (or rebase, merge). The same holds for your own commands. Put what waits under NEEDS
   YOU, for when the user is back.
