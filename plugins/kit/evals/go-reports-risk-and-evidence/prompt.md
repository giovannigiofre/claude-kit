---
max_turns: 60
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Bash, Edit, Write, Agent, Skill, AskUserQuestion]
runs: 1
---

/kit:go no-pr no-babysit - I added an --upper flag to greet.py so `python3 greet.py ada --upper` prints the greeting in capitals.
