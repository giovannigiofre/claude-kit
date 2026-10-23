---
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, TaskCreate, TaskUpdate, "Bash(python3 *)"]
runs: 1
---

Make the retry in llm.py back off exponentially.
