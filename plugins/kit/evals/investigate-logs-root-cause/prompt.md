---
max_turns: 60
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Agent, Write, Edit, TaskCreate, TaskUpdate, "Bash(python3 *)", "Bash(git *)"]
runs: 1
---

The nightly-ingest job failed last night. I downloaded the logs from the GCP console: .debug/fail.json is last night's failed run and .debug/ok.json is the run from the night before, which worked. Find the cause and fix it.
