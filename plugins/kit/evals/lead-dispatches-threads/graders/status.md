---
type: llm
---

PASS if the run splits the request into three items (two ship items and one scout item about add()), records them on a board file, starts background threads for them (at most 2 working at once), and the replies to the user are short (at most about four lines: what started, what is ready, what needs the user) rather than long transcripts. Reporting the add() bug as the scout finding is a plus.
FAIL if everything is done in one long foreground pass with no board, or the reply claims items are done without evidence from running their checks.
