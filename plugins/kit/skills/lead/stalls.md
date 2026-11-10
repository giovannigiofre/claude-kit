# A quiet or stuck thread

The kit's watchdog wakes you when a thread has written nothing for a while (`silent`), has waited
minutes on background work that cannot wake it (`stuck`), or has a command past its deadline
(`job`). The wake names what it found: a command that ended, a holder, a permission prompt.

Before you act, look, with no guessing:

1. Its transcript's last lines (`tail -c 3000 <tasks dir>/<agent id>.output`, read with care: it
   is large JSONL). A pending `tool_use` with no `tool_result` is what it is inside.
2. The output file of each command it started (`tail -c 2000 <tasks dir>/<task id>.output`): one
   ending with `[exited with code N]` or `[killed]` has finished, and its last lines are the result.

Then, by what blocks it:

- **A permission prompt** (the wake says so, or the pending tool call is one an ask rule covers,
  such as `git push`): only the person can answer it. Put it under NEEDS YOU, naming the thread
  and the command. A SendMessage only queues behind the prompt. If the person would rather not
  answer, stop the thread (below) and tell it to run that step in the foreground.
- **A command that ended, and the thread has not acted**: `TaskStop <agent id>`, then
  `SendMessage <agent id>` with the result lines from its output file and what to do next. A
  stopped thread resumes from its transcript, with its context intact.
- **A holder** (a loop that keeps a lock or waits for a file until the thread acts): the thread
  cannot act while it waits on it. `TaskStop <task id>` of the holder, then resume the thread as
  above, telling it to run the step under the lock as one command (`lockf <lock> <command>`).
- **A command still running within its deadline**: nothing; Claude Code wakes the thread when it
  ends. Past its deadline: read its output; stop it if it hangs.

Check what a holder blocks before saying so: read the lock's other takers' output files; a suite
that already finished is not blocked. One recovery per stall: after the SendMessage, wait for the
thread's next event, not for another wake. Log it on the item (`I log <id> working "stalled on
<cause>; resumed"`), and when the same cause comes back, put a line in the brief.
