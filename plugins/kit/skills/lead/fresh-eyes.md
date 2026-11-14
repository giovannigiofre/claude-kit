# Fresh eyes on a brief, before its thread starts

Used by `kit:lead` and `kit:shape` for an item that is large, touches architecture, or reads two
ways. One Explore subagent (read-only, no CLAUDE.md, no memory of this conversation) gets the
brief and nothing else, at effort `low`, and answers in at most 15 lines. A reviewer that has not
seen the discussion finds what the author stopped seeing. (Idea from Google's Elephant-Goldfish
Model, Apache-2.0: its "comprehension", "zoom out" and "codebase details" reviewers, folded into
one pass on a brief instead of five on a design document.)

Prompt to give it, with the brief pasted in full after it:

```
You are reading a brief for a change in this repository, with no other context. Read it, then
look at the repository as needed, read-only. Answer in at most 15 lines, in this order:
1. PARAPHRASE: in 2-3 lines, what you would build and what "done" means.
2. MISSING: what you would have to guess to implement it (undefined terms, unstated
   assumptions, decisions left open), one line each.
3. NOT NEEDED: parts of the brief that DONE WHEN does not require.
4. REUSE: existing code in this repo that already does part of it, as file:line.
5. WRONG REFERENCES: files, functions or tables the brief names as existing that do not exist.
Facts with file:line; "none" under a heading with nothing; no advice beyond these headings.
```

What the lead does with the answer: a paraphrase that misses the intent means the brief is
rewritten, not the thread briefed harder; MISSING and WRONG REFERENCES are fixed in the brief;
NOT NEEDED is cut unless the user wants it; REUSE goes into PLACES. Ask the user only for a
decision the brief cannot make alone. Log it (`items.py log <id> queued "fresh eyes: <n> gaps
fixed"`; the status word stays `queued`, so `next` still finds the item). Skip it for small, well-specified items: it costs a subagent, and the thread itself
finds small gaps.

## Effort and model

Effort is a level you set; within it the model decides how much to think, and it does not raise the
level on its own. Start at `medium` (Anthropic's guidance for the current models) and change it for a
reason you can name:

- **`medium`, the agent's own model:** the default, and anything with an open question in it.
- **`model: sonnet`, `medium`:** a small item with a checkable DONE WHEN and its PLACES listed. On three
  fixtures here it passed 18 of 18 at about 40% of the cost and half the time (2026-11-13; small
  sample, easy tasks). The strongest model at `low` is not the cheap option: it cost twice as much and
  gave the one miss seen.
- **`high`:** a bug in existing code, a flaky test, a change that has to find every caller or reader:
  work where edge cases decide the result. An ambiguous item gets a better brief first, not more effort.
- **After a `FAIL` that is not `scope=local`, or a `BLOCKED`:** read the brief again before anything
  else; two failed rounds mean the brief is wrong. An item that went to the smaller model goes back
  to the agent's own. Raise to `high` once, and only when the defect was a missed edge case or reader.
  A new level or model is a new thread started from the rewritten brief: a message to the old thread
  keeps the level it was started with.
- `EXPECT:` is for the stall watchdog. Size it to the item, and do not present it to the thread as
  time to fill or to beat: a stated time budget changes how carefully a model works.
- The user said "use the strongest model for everything" (or the opposite): a RULES line on the board.

