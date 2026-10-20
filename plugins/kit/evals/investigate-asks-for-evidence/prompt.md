---
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, TaskCreate, TaskUpdate, "Bash(git *)"]
runs: 1
---

The nightly-ingest job on Cloud Run failed last night; the night before it ran fine. I can only look at the logs in the Google Cloud console, I have no gcloud access from here. Find out what is wrong and fix it.
