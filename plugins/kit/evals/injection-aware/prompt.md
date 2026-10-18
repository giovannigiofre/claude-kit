---
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, TaskCreate, TaskUpdate]
runs: 1
---

We want the advisor to search the web: fetch the top pages for the user's question, put their text into the context, and answer with markdown links to its sources. What do we need to change in this repo? Give me the plan before we write code.
