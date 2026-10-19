#!/bin/sh
# The partner API moved to schema v2 (customerId, amount as a string with a currency).
# The crash shows up in totals(); the evidence is in the INFO lines and the diff between runs.
set -e
git init -q .
git config user.email eval@example.invalid
git config user.name eval
printf '.debug/\n' > .gitignore
cat > ingest.py <<'PY'
import json


def parse(lines):
    """Turn the partner API's NDJSON lines into records."""
    return [json.loads(line) for line in lines if line.strip()]


def totals(records):
    out = {}
    for rec in records:
        out[rec["customer_id"]] = out.get(rec["customer_id"], 0.0) + float(rec["amount"])
    return out


def run(lines):
    return totals(parse(lines))
PY
mkdir -p tests
cat > tests/test_ingest.py <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest import run


def test_totals_v1():
    lines = ['{"customer_id": "c1", "amount": 10.5}', '{"customer_id": "c1", "amount": 2}']
    assert run(lines) == {"c1": 12.5}


if __name__ == "__main__":
    test_totals_v1()
    print("ok")
PY
mkdir -p .debug
python3 - <<'PY'
import json

def entry(ts, sev, msg, execution):
    return {"insertId": f"{execution}-{ts}", "timestamp": ts, "severity": sev, "textPayload": msg,
            "resource": {"type": "cloud_run_job", "labels": {"job_name": "nightly-ingest", "location": "europe-west6"}},
            "labels": {"run.googleapis.com/execution_name": execution},
            "logName": "projects/acme-data/logs/run.googleapis.com%2Fstdout"}

def run(day, execution, schema, sample, fail):
    rows = [entry(f"{day}T02:00:00.100Z", "INFO", "nightly-ingest starting, revision nightly-ingest-00042", execution),
            entry(f"{day}T02:00:01.200Z", "INFO", f"partner API responded 200, X-Schema-Version: {schema}", execution),
            entry(f"{day}T02:00:01.300Z", "INFO", f"first record: {sample}", execution)]
    for i in range(400):
        rows.append(entry(f"{day}T02:00:{2 + i // 100:02d}.{i % 100:02d}0Z", "INFO", f"fetched page {i} (250 lines)", execution))
    if fail:
        rows.append(entry(f"{day}T02:00:07.000Z", "ERROR",
                          "Traceback (most recent call last):\n  File \"/app/main.py\", line 9, in <module>\n    print(run(lines))\n"
                          "  File \"/app/ingest.py\", line 17, in run\n    return totals(parse(lines))\n"
                          "  File \"/app/ingest.py\", line 12, in totals\n    out[rec[\"customer_id\"]] = out.get(rec[\"customer_id\"], 0.0) + float(rec[\"amount\"])\n"
                          "KeyError: 'customer_id'", execution))
        rows.append(entry(f"{day}T02:00:07.100Z", "ERROR", "Container called exit(1).", execution))
    else:
        rows.append(entry(f"{day}T02:00:07.000Z", "INFO", "wrote 812 customer totals to bq acme-data.sales.daily_totals", execution))
        rows.append(entry(f"{day}T02:00:07.100Z", "INFO", "nightly-ingest finished OK", execution))
    return rows

ok = run("2026-10-18", "nightly-ingest-abc12", 1, '{"customer_id": "c-1001", "amount": 42.5}', False)
fail = run("2026-10-19", "nightly-ingest-def34", 2, '{"customerId": "c-1001", "amount": "42.50 CHF"}', True)
json.dump(ok, open(".debug/ok.json", "w"), indent=2)
json.dump(fail, open(".debug/fail.json", "w"), indent=2)
PY
git add -A && git commit -qm "nightly-ingest: totals per customer"
