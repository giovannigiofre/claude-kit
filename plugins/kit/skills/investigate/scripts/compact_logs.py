#!/usr/bin/env python3
"""Compact and summarize log exports so an agent can read them without flooding context.

Accepts JSON (array or {"entries": [...]}) such as GCP Logs Explorer downloads,
NDJSON, CSV (CloudWatch, Azure, flattened GCP CSV) and plain-text logs.

Examples:
  compact_logs.py .debug/fail.json                       # summary only
  compact_logs.py .debug/fail.json --diff .debug/ok.json # what is new in the failing run
  compact_logs.py .debug/fail.json --min-severity ERROR --limit 50
  compact_logs.py .debug/fail.json --trace abc123 --min-severity DEFAULT
  compact_logs.py .debug/fail.json --grep "timeout|refused" --full
  compact_logs.py .debug/fail.json --window 20           # lines around the first error
  compact_logs.py .debug/fail.json --out .debug/fail.tsv # write all compact lines to a file
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict

SEV_RANK = {
    "DEFAULT": 0, "TRACE": 100, "DEBUG": 100, "INFO": 200, "NOTICE": 300,
    "WARN": 400, "WARNING": 400, "ERROR": 500, "ERR": 500, "SEVERE": 500,
    "CRITICAL": 600, "FATAL": 600, "ALERT": 700, "EMERGENCY": 800,
}
SEV_WORD = re.compile(r"\b(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|SEVERE|CRITICAL|FATAL|ALERT|EMERGENCY)\b")
ERRORISH = re.compile(r"(Traceback|Exception|Error\b|error:|panic:|FATAL|Unhandled|failed|refused|timed? ?out)", re.I)
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?")

TS_KEYS = ["timestamp", "@timestamp", "time", "ts", "receiveTimestamp", "asctime", "date", "TimeGenerated"]
SEV_KEYS = ["severity", "level", "levelname", "log.level", "jsonPayload.severity",
            "jsonPayload.level", "jsonPayload.levelname", "SeverityLevel"]
TRACE_KEYS = ["trace", "jsonPayload.trace", "logging.googleapis.com/trace",
              "jsonPayload.logging.googleapis.com/trace", "trace_id", "traceId",
              "jsonPayload.trace_id", "request_id", "requestId", "jsonPayload.request_id",
              "jsonPayload.requestId", "@requestId", "labels.run.googleapis.com/execution_name",
              "labels.execution_name", "OperationId"]
SOURCE_KEYS = ["resource.labels.service_name", "resource.labels.job_name",
               "resource.labels.container_name", "resource.labels.function_name",
               "service", "jsonPayload.service", "logger", "jsonPayload.logger", "@logStream",
               "logName", "AppRoleName"]
MSG_KEYS = ["textPayload", "jsonPayload.message", "jsonPayload.msg", "jsonPayload.error",
            "message", "msg", "@message", "protoPayload.status.message", "Message", "log"]


def flatten(obj, prefix="", out=None):
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}"
            if isinstance(v, dict) and v:
                flatten(v, key + ".", out)
            else:
                out[key] = v
    else:
        out[prefix.rstrip(".") or "value"] = obj
    return out


def first(d, keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def load(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    stripped = text.lstrip()
    if path.lower().endswith(".csv"):
        return [("csv", row) for row in csv.DictReader(text.splitlines())]
    if stripped.startswith("["):
        try:
            return [("json", e) for e in json.loads(text)]
        except json.JSONDecodeError:
            pass
    if stripped.startswith("{"):
        try:
            data = json.loads(text)
            for key in ("entries", "events", "results", "logs", "data"):
                if isinstance(data.get(key), list):
                    return [("json", e) for e in data[key]]
            return [("json", data)]
        except json.JSONDecodeError:
            rows = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(("json", json.loads(line)))
                except json.JSONDecodeError:
                    rows.append(("text", line))
            return rows
    return [("text", line) for line in merge_multiline(text.splitlines())]


def merge_multiline(lines):
    """Glue stack-trace continuation lines to the line that started the record."""
    out = []
    nonempty = [l for l in lines if l.strip()]
    ts_lines = sum(1 for l in nonempty if TS_RE.match(l.strip()))
    timestamped = nonempty and ts_lines / len(nonempty) >= 0.3
    for line in lines:
        if not line.strip():
            continue
        if timestamped:
            starts_record = bool(TS_RE.match(line.strip()))
            glue = not starts_record
        else:
            starts_record = bool(SEV_WORD.match(line.strip()))
            glue = not starts_record and (line[:1].isspace() or line.startswith(("Traceback", "Caused by", "at ")))
        if out and glue:
            out[-1] += "\n" + line
        else:
            out.append(line)
    return out


def normalize(kind, raw, idx):
    if kind == "json" and not isinstance(raw, dict):
        kind, raw = "text", str(raw)
    if kind == "text":
        m = TS_RE.search(raw)
        s = SEV_WORD.search(raw[:200])
        sev = s.group(1).upper() if s else ("ERROR" if ERRORISH.search(raw) else "DEFAULT")
        return {"i": idx, "ts": m.group(0) if m else "", "sev": sev, "trace": "", "src": "", "msg": raw}
    flat = flatten(raw) if kind == "json" else {k: v for k, v in raw.items() if k}
    ts = str(first(flat, TS_KEYS) or "")
    msg = first(flat, MSG_KEYS)
    if msg is None:
        req = {k: flat.get(f"httpRequest.{k}") for k in ("requestMethod", "requestUrl", "status", "latency")}
        if any(req.values()):
            msg = " ".join(str(v) for v in req.values() if v)
        else:
            payload = raw.get("jsonPayload") if kind == "json" and isinstance(raw, dict) else None
            msg = json.dumps(payload if payload else raw, ensure_ascii=False, default=str)
    msg = str(msg)
    sev = first(flat, SEV_KEYS)
    sev = str(sev).upper() if sev is not None and not isinstance(sev, (int, float)) else ""
    if sev not in SEV_RANK:
        s = SEV_WORD.search(msg[:200])
        sev = s.group(1).upper() if s else ("ERROR" if ERRORISH.search(msg) else (sev or "DEFAULT"))
        if sev not in SEV_RANK:
            sev = "DEFAULT"
    status = flat.get("httpRequest.status")
    if status and str(status).isdigit() and int(status) >= 500 and SEV_RANK[sev] < 500:
        sev = "ERROR"
    trace = str(first(flat, TRACE_KEYS) or "")
    trace = trace.rsplit("/", 1)[-1]
    src = str(first(flat, SOURCE_KEYS) or "")
    src = src.rsplit("/", 1)[-1]
    return {"i": idx, "ts": ts, "sev": sev, "trace": trace, "src": src, "msg": msg}


SIG_SUBS = [
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.I), "<hex>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "<email>"),
    (re.compile(r"https?://\S+"), "<url>"),
    (TS_RE, "<ts>"),
    (re.compile(r"(['\"]).{1,80}?\1"), "<str>"),
    (re.compile(r"\b\d+(?:\.\d+)?(?:ms|us|ns|s|m|h|[kmg]i?b|%)?\b", re.I), "<n>"),
]
LEADING_NOISE = re.compile(r"^(?:<ts>\s*)?(?:\[?\s*(?:TRACE|DEBUG|INFO|NOTICE|WARNING|WARN|ERROR|ERR|SEVERE|CRITICAL|FATAL|ALERT|EMERGENCY)\b\s*\]?:?\s*)?", re.I)


def signature(msg):
    lines = [l for l in msg.splitlines() if l.strip()]
    line = lines[0] if lines else ""
    # Python tracebacks: the exception line (last) is the useful one
    if any(l.lstrip().startswith("Traceback") for l in lines[:3]) and len(lines) > 1:
        line = lines[-1]
    for rx, rep in SIG_SUBS:
        line = rx.sub(rep, line)
    line = LEADING_NOISE.sub("", line.strip())
    return re.sub(r"\s+", " ", line).strip()[:160]


def rank(sev):
    return SEV_RANK.get(sev, 0)


def compact_line(e, full=False, width=300):
    msg = e["msg"] if full else e["msg"].splitlines()[0] if e["msg"].strip() else ""
    extra = len(e["msg"].splitlines()) - 1
    if not full:
        msg = msg[:width] + (f"  (+{extra} lines)" if extra > 0 else "")
    return "\t".join([str(e["i"]), e["ts"], e["sev"], e["trace"][:16], e["src"], msg])


def read_entries(path):
    entries = [normalize(k, r, i) for i, (k, r) in enumerate(load(path))]
    if entries and all(e["ts"] for e in entries):
        entries.sort(key=lambda e: e["ts"])
        for n, e in enumerate(entries):
            e["i"] = n
    return entries


def summarize(path, entries, top):
    print(f"# {path}: {len(entries)} entries")
    if not entries:
        return
    ts = [e["ts"] for e in entries if e["ts"]]
    if ts:
        print(f"time range: {min(ts)} -> {max(ts)}")
    sev_counts = Counter(e["sev"] for e in entries)
    print("severity:", ", ".join(f"{k}={v}" for k, v in sorted(sev_counts.items(), key=lambda kv: -rank(kv[0]))))
    srcs = Counter(e["src"] for e in entries if e["src"])
    if srcs:
        print("sources:", ", ".join(f"{k}={v}" for k, v in srcs.most_common(8)))

    bad = [e for e in entries if rank(e["sev"]) >= 400]
    pool = bad if bad else entries
    sigs = defaultdict(list)
    for e in pool:
        sigs[signature(e["msg"])].append(e)
    label = "WARNING+" if bad else "all (no severities found)"
    print(f"\n## top signatures ({label})  count | max sev | first ts | first idx | signature")
    for sig, es in sorted(sigs.items(), key=lambda kv: (-max(rank(x["sev"]) for x in kv[1]), -len(kv[1])))[:top]:
        print(f"{len(es):5d} | {max((x['sev'] for x in es), key=rank):8s} | {es[0]['ts'] or '-'} | {es[0]['i']} | {sig}")

    errors = [e for e in entries if rank(e["sev"]) >= 500]
    if errors:
        e = errors[0]
        print(f"\n## first error (idx {e['i']})")
        print("\n".join(e["msg"].splitlines()[:25]))
        traces = Counter(x["trace"] for x in errors if x["trace"])
        if traces:
            print("\n## traces/runs with errors:", ", ".join(f"{t} ({c})" for t, c in traces.most_common(10)))
            print("   -> drill down with --trace <id> --min-severity DEFAULT")


def diff(bad_entries, good_entries, top):
    def light(msg):
        lines = [l for l in msg.splitlines() if l.strip()]
        line = lines[0] if lines else ""
        if any(l.lstrip().startswith("Traceback") for l in lines[:3]) and len(lines) > 1:
            line = lines[-1]
        for rx, rep in SIG_SUBS[:2] + [(TS_RE, "<ts>")]:
            line = rx.sub(rep, line)
        return line.strip()[:200]

    bad_sigs = Counter(signature(e["msg"]) for e in bad_entries)
    good_sigs = Counter(signature(e["msg"]) for e in good_entries)
    example, sev_of = {}, {}
    for e in bad_entries + good_entries:
        example.setdefault(signature(e["msg"]), light(e["msg"]))
    for e in bad_entries:
        s = signature(e["msg"])
        if rank(e["sev"]) >= rank(sev_of.get(s, "DEFAULT")):
            sev_of[s] = e["sev"]

    def show(sig, count):
        # rare lines: the concrete line says more than its normalized shape
        return example[sig] if count <= 3 else sig

    only_bad = [(s, c) for s, c in bad_sigs.items() if s not in good_sigs]
    only_bad.sort(key=lambda sc: (-rank(sev_of.get(sc[0], "DEFAULT")), -sc[1]))
    print(f"\n## ONLY in the failing export ({len(only_bad)})  count | max sev | line (or its shape if frequent)")
    for s, c in only_bad[:top]:
        print(f"{c:5d} | {sev_of.get(s, ''):8s} | {show(s, c)}")
    only_good = [(s, c) for s, c in good_sigs.items() if s not in bad_sigs]
    only_good.sort(key=lambda sc: -sc[1])
    print(f"\n## ONLY in the working export ({len(only_good)}): steps that never happened in the failing run?")
    for s, c in only_good[:top]:
        print(f"{c:5d} | {show(s, c)}")

    # Same message shape, different values (versions, schemas, config, counts): rare lines only,
    # because those are the startup/config lines where a changed value usually matters.
    by_sig_bad, by_sig_good = defaultdict(set), defaultdict(set)
    for e in bad_entries:
        by_sig_bad[signature(e["msg"])].add(light(e["msg"]))
    for e in good_entries:
        by_sig_good[signature(e["msg"])].add(light(e["msg"]))
    changed = [s for s in bad_sigs if s in good_sigs and bad_sigs[s] <= 3 and good_sigs[s] <= 3
               and by_sig_bad[s] != by_sig_good[s]]
    print(f"\n## same line, different values ({len(changed)}): working -> failing")
    for s in changed[:top]:
        print(f"  ok:   {' | '.join(sorted(by_sig_good[s]))}")
        print(f"  fail: {' | '.join(sorted(by_sig_bad[s]))}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file")
    p.add_argument("--diff", metavar="GOOD_FILE", help="export of a working run to compare against")
    p.add_argument("--min-severity", default=None, help="DEFAULT, DEBUG, INFO, WARNING, ERROR, CRITICAL")
    p.add_argument("--trace", help="only entries whose trace/request/run id contains this")
    p.add_argument("--grep", help="regex on the message (case-insensitive)")
    p.add_argument("--window", type=int, help="print N entries before/after the first error (or --around)")
    p.add_argument("--around", type=int, help="entry index to center --window on")
    p.add_argument("--limit", type=int, default=200, help="max lines to print (default 200)")
    p.add_argument("--top", type=int, default=15, help="signatures to show in summaries")
    p.add_argument("--full", action="store_true", help="print full multi-line messages")
    p.add_argument("--out", help="write all compact lines (TSV) to this file")
    a = p.parse_args()

    entries = read_entries(a.file)

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("idx\tts\tseverity\ttrace\tsource\tmessage\n")
            for e in entries:
                f.write(compact_line(e, full=False, width=1000).replace("\n", " ") + "\n")
        print(f"wrote {len(entries)} compact lines to {a.out}", file=sys.stderr)

    filtering = any(x is not None for x in (a.min_severity, a.trace, a.grep, a.window))
    if not filtering:
        summarize(a.file, entries, a.top)
        if a.diff:
            good = read_entries(a.diff)
            print(f"\n# compared with {a.diff}: {len(good)} entries")
            diff(entries, good, a.top)
        return

    sel = entries
    if a.window is not None:
        center = a.around
        if center is None:
            errs = [e["i"] for e in entries if rank(e["sev"]) >= 500]
            center = errs[0] if errs else 0
        sel = [e for e in entries if center - a.window <= e["i"] <= center + a.window]
    if a.trace:
        sel = [e for e in sel if a.trace in e["trace"]]
    if a.min_severity:
        floor = SEV_RANK.get(a.min_severity.upper(), 0)
        sel = [e for e in sel if rank(e["sev"]) >= floor]
    elif a.window is None and a.trace is None and a.grep is None:
        sel = [e for e in sel if rank(e["sev"]) >= 400]
    if a.grep:
        rx = re.compile(a.grep, re.I)
        sel = [e for e in sel if rx.search(e["msg"])]

    print(f"# {len(sel)} matching entries (showing up to {a.limit})")
    print("idx\tts\tseverity\ttrace\tsource\tmessage")
    for e in sel[: a.limit]:
        print(compact_line(e, full=a.full))
    if len(sel) > a.limit:
        print(f"... {len(sel) - a.limit} more; narrow the filter or raise --limit")


if __name__ == "__main__":
    main()
