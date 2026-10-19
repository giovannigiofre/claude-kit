#!/usr/bin/env python3
"""Self-check for compact_logs.py.

Run: python3 plugins/kit/skills/investigate/tests/test_compact_logs.py   (exit 0 = all good)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "compact_logs.py"


def run(*args):
    out = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout


def gcp(ts, sev, text, execution="exec-1", **extra):
    entry = {"timestamp": ts, "severity": sev, "textPayload": text,
             "resource": {"type": "cloud_run_job", "labels": {"job_name": "ingest"}},
             "labels": {"run.googleapis.com/execution_name": execution}}
    entry.update(extra)
    return entry


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        tb = "Traceback (most recent call last):\n  File \"a.py\", line 3, in f\nKeyError: 'customer_id'"
        fail = [gcp("2026-10-19T02:00:01Z", "INFO", "schema version 2", "e2"),
                *[gcp(f"2026-10-19T02:00:{i % 50 + 2:02d}Z", "INFO", f"page {i} ok", "e2") for i in range(300)],
                gcp("2026-10-19T02:01:00Z", "ERROR", tb, "e2"),
                gcp("2026-10-19T02:01:01Z", "DEFAULT", None, "e2",
                    httpRequest={"requestMethod": "POST", "requestUrl": "/hook", "status": 503})]
        ok = [gcp("2026-10-18T02:00:01Z", "INFO", "schema version 1", "e1"),
              gcp("2026-10-18T02:00:02Z", "INFO", "page 0 ok", "e1"),
              gcp("2026-10-18T02:01:00Z", "INFO", "finished OK", "e1")]
        (tmp / "fail.json").write_text(json.dumps(fail))
        (tmp / "ok.json").write_text(json.dumps(ok))

        out = run(tmp / "fail.json")
        assert "303 entries" in out, out
        assert "KeyError" in out and "first error" in out, "traceback signature uses the exception line"
        assert "POST /hook" in out, "an httpRequest with status >= 500 counts as an error"
        assert "e2 (2)" in out, "errors are grouped by execution id"
        assert "page 17 ok" not in out, "the summary does not dump INFO lines"

        out = run(tmp / "fail.json", "--diff", tmp / "ok.json")
        assert "KeyError: 'customer_id'" in out, "rare lines appear concretely in the diff"
        assert "finished OK" in out.split("ONLY in the working export")[1], "missing steps are listed"
        changed = out.split("same line, different values")[1]
        assert "schema version 1" in changed and "schema version 2" in changed, "changed values are shown"

        out = run(tmp / "fail.json", "--trace", "e2", "--min-severity", "DEFAULT", "--limit", "5")
        assert "more; narrow the filter" in out
        out = run(tmp / "fail.json", "--window", "1", "--full")
        assert "line 3, in f" in out, "--full keeps the stack trace"

        (tmp / "app.log").write_text(
            "2026-10-19 14:00:01,1 INFO started\n"
            "2026-10-19 14:00:02,1 ERROR unhandled exception\nTraceback (most recent call last):\n"
            "  File \"app.py\", line 42, in h\nValueError: bad 'abc'\n"
            "2026-10-19 14:00:03,5 WARNING slow query 1532ms\n")
        out = run(tmp / "app.log")
        assert "3 entries" in out, "continuation lines stay with their record"
        assert "| slow query <n>" in out, "level words and numbers are stripped from signatures"

        (tmp / "cw.csv").write_text('@timestamp,@message,@logStream\n'
                                    '2026-10-19 14:00:01.000,"Task timed out after 30.00 seconds",fn/abc\n')
        out = run(tmp / "cw.csv", "--grep", "timed")
        assert "1 matching" in out and "ERROR" in out, "error words set the severity when none is given"

        (tmp / "x.ndjson").write_text('{"level":"error","msg":"boom","trace_id":"t9"}\nplain line\n')
        out = run(tmp / "x.ndjson", "--min-severity", "ERROR")
        assert "boom" in out and "t9" in out

        (tmp / "empty.json").write_text("")
        assert "0 entries" in run(tmp / "empty.json")

        out_file = tmp / "all.tsv"
        run(tmp / "fail.json", "--out", out_file)
        assert len(out_file.read_text().splitlines()) == 304, "header + one line per entry"
    print("compact_logs: all checks passed")


if __name__ == "__main__":
    main()
