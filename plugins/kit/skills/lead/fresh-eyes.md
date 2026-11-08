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
decision the brief cannot make alone. Log it (`items.py log <id> checked "fresh eyes: <n> gaps
fixed"`). Skip it for small, well-specified items: it costs a subagent, and the thread itself
finds small gaps.
