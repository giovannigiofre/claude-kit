#!/bin/sh
# A small Cloud Run job repo. No logs in the repo: they exist only in the user's console.
set -e
git init -q .
git config user.email eval@example.invalid
git config user.name eval
cat > README.md <<'MD'
# nightly-ingest

Cloud Run job `nightly-ingest` in project `acme-data`, region europe-west6. Runs at 02:00,
reads yesterday's orders from the partner API and writes totals per customer to BigQuery.
MD
cat > ingest.py <<'PY'
import json
import os
import urllib.request


def fetch(day):
    url = os.environ["PARTNER_API"] + f"/orders?day={day}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return [json.loads(line) for line in r.read().decode().splitlines() if line.strip()]


def totals(records):
    out = {}
    for rec in records:
        out[rec["customer_id"]] = out.get(rec["customer_id"], 0) + float(rec["amount"])
    return out
PY
git add -A && git commit -qm "nightly-ingest job"
