# GCP: exporting logs from the Logs Explorer UI

Use when the user has console access but no `gcloud` and no Cloud Logging MCP server (Google's
remote one is `https://logging.googleapis.com/mcp`; it needs log-read IAM). With either of those,
query directly with the same filters and skip the export. Otherwise give the user these steps,
filled in with the real names and times, in one message.

## Steps for the user

1. Console → **Logging → Logs Explorer**. Check the project selector at the top is the right project.
2. Time range: custom, from ~15 min before to ~15 min after the failure.
3. Switch on "Show query" and paste the query below (replace the CAPS placeholders).
4. **Run query**, then use the **Download** option of the results (it opens the "Download logs" dialog).
5. Format **JSON**. If the download fails or is slow: lower "Maximum log entries", narrow the time range.
6. Save as `.debug/fail.json`.
7. Repeat steps 2–6 for a time window or run that **worked**, same query → `.debug/ok.json`.
8. Also send: the trace ID or execution name of one failing request/run (click the entry → copy `trace` or the label), and the revision that was serving.

Downloads from the UI are meant for small exports; that's fine here, we want a narrow slice anyway.

## Queries to give the user

Cloud Run service:
```
resource.type="cloud_run_revision"
resource.labels.service_name="SERVICE"
severity>=WARNING
```

Cloud Run job — one execution (no severity filter: the INFO lines before the error matter):
```
resource.type="cloud_run_job"
resource.labels.job_name="JOB"
labels."run.googleapis.com/execution_name"="EXECUTION"
```

One request end-to-end (all severities, all services):
```
trace="projects/PROJECT/traces/TRACE_ID"
```

HTTP errors only:
```
resource.type="cloud_run_revision"
httpRequest.status>=500
```

GKE container:
```
resource.type="k8s_container"
resource.labels.namespace_name="NAMESPACE"
resource.labels.container_name="CONTAINER"
severity>=WARNING
```

Cloud Functions gen2 run on Cloud Run → use the Cloud Run service query with the function name. Gen1: `resource.type="cloud_function"` + `resource.labels.function_name="NAME"`.

Free-text search for an ID anywhere in the payload: add a line with just `"THE_ID"`.

## Processing

With the skill's `scripts/compact_logs.py` (full path in SKILL.md step 1):

```
compact_logs.py .debug/fail.json --diff .debug/ok.json
compact_logs.py .debug/fail.json --trace EXECUTION_OR_TRACE_ID --min-severity DEFAULT
```

Start from the summary (error signatures, first error, signatures only in the failing run), then pull the lines around the first error with `--window`.

## After the fix

Tell the user to re-run the same query on a window after the deploy and confirm the error signature is gone (or send the new export to check).
