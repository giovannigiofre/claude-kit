#!/usr/bin/env python3
"""Schema consistency lint: checks the JSON-LD a page already has, never proposes new markup.

  schema_lint.py <dir> [--out schema.json]

<dir> is either a run's html/ folder (files named in _paths.tsv: "<file>\\t<path>") or a built site
(dist/: every **/index.html, its path taken from the folder). Exit 1 when any page has an error.

Checks (research-2.md, capability 9):
  error  JSON-LD that does not parse
  error  WebApplication without name, url, applicationCategory or isAccessibleForFree
  error  dateModified that differs from the visible "verified/reviewed" date on the page
  warn   aggregateRating or review: only with real user ratings, which neither site has
  info   FAQPage or HowTo: no rich result since 7 May 2026, never pitch it as a win
"""

import argparse
import json
import re
import sys
from pathlib import Path

LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
TIME = re.compile(r"<time([^>]*)>(.*?)</time>", re.S | re.I)
WEBAPP_REQUIRED = ("name", "url", "applicationCategory", "isAccessibleForFree")


def nodes(data):
    """Every dict in a JSON-LD document, @graph and nested values included."""
    if isinstance(data, list):
        for x in data:
            yield from nodes(x)
    elif isinstance(data, dict):
        yield data
        for v in data.values():
            if isinstance(v, (dict, list)):
                yield from nodes(v)


def top_level(data):
    """The page's own entities: the document's nodes and @graph members, not nested references
    (a CollectionPage's hasPart lists other pages' apps by name and url only)."""
    items = data if isinstance(data, list) else [data]
    for x in items:
        if isinstance(x, dict):
            yield x
            for g in x.get("@graph") or []:
                if isinstance(g, dict):
                    yield g


def types(node) -> set[str]:
    t = node.get("@type")
    return set(t) if isinstance(t, list) else {t} if isinstance(t, str) else set()


def visible_dates(page: str) -> set[str]:
    """ISO dates of <time> elements: the datetime attribute, or text as dd/mm/yyyy, dd.mm.yyyy or yyyy-mm-dd."""
    out = set()
    for attrs, inner in TIME.findall(page):
        m = re.search(r'datetime=["\'](\d{4}-\d{2}-\d{2})', attrs)
        if m:
            out.add(m.group(1))
            continue
        inner = re.sub(r"<[^>]+>", "", inner).strip()
        m = re.match(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})$", inner)
        if m:
            out.add(f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}")
        elif re.match(r"\d{4}-\d{2}-\d{2}$", inner):
            out.add(inner)
    return out


def lint_page(page: str) -> list[dict]:
    issues = []
    modified = set()
    for i, block in enumerate(LD.findall(page)):
        try:
            data = json.loads(block)
        except json.JSONDecodeError as e:
            issues.append({"code": "jsonld-parse", "severity": "error", "detail": f"block {i}: {e.msg}"})
            continue
        own = [id(n) for n in top_level(data)]
        for node in nodes(data):
            t = types(node)
            if "WebApplication" in t and id(node) in own:
                missing = [k for k in WEBAPP_REQUIRED if k not in node]
                if missing:
                    issues.append({"code": "webapp-incomplete", "severity": "error", "detail": f"WebApplication misses {missing}"})
            if "aggregateRating" in node or "review" in node:
                issues.append({"code": "ratings", "severity": "warn", "detail": "aggregateRating/review: only with real user ratings"})
            if t & {"FAQPage", "HowTo"}:
                issues.append({"code": "faq-howto", "severity": "info", "detail": f"{sorted(t & {'FAQPage', 'HowTo'})}: no rich result since May 2026"})
            if isinstance(node.get("dateModified"), str) and "Dataset" not in t:
                modified.add(node["dateModified"][:10])
    shown = visible_dates(page)
    if modified and shown:
        for d in sorted(modified - shown):
            issues.append({"code": "date-mismatch", "severity": "error",
                           "detail": f"dateModified {d} is not the visible date ({', '.join(sorted(shown))})"})
    elif modified and not shown:
        issues.append({"code": "date-not-visible", "severity": "info", "detail": f"dateModified {sorted(modified)} has no machine-readable visible date"})
    return issues


def pages(root: Path):
    tsv = root / "_paths.tsv"
    if tsv.exists():
        for line in tsv.read_text().splitlines():
            name, _, path = line.partition("\t")
            f = root / name
            if f.exists():
                yield path, f
        return
    for f in sorted(root.rglob("index.html")):
        rel = f.parent.relative_to(root).as_posix()
        yield "/" if rel == "." else f"/{rel}/", f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out")
    a = ap.parse_args()
    report = []
    for path, f in pages(Path(a.dir)):
        issues = lint_page(f.read_text(errors="replace"))
        if issues:
            report.append({"path": path, "issues": issues})
    errors = sum(1 for p in report for i in p["issues"] if i["severity"] == "error")
    out = {"pages_with_issues": len(report), "errors": errors, "pages": report}
    if a.out:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for p in report:
        for i in p["issues"]:
            if i["severity"] != "info":
                print(f"{i['severity']:5} {p['path']}  {i['code']}: {i['detail']}")
    print(f"schema lint: {errors} errors on {len(report)} pages with issues")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
