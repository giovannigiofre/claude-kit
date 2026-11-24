#!/usr/bin/env python3
"""Flag the "AI look" in changed UI files: python3 slop_lint.py FILE...

Our own implementation of the rule IDs Open Design's artifact lint uses
(apps/daemon/src/lint-artifact.ts at open-design-v0.27.2). P0 must be fixed, P1 fixed or
justified in the handoff. Exit code 1 when any P0 is found. A heuristic: a finding is a
prompt to look, and a rule the project's own design system requires is not a finding.
"""
import re
import sys
from pathlib import Path

PURPLE = ["#a855f7", "#9333ea", "#7c3aed", "#6d28d9", "#581c87", "#8b5cf6", "#a78bfa",
          "#c4b5fd", "#ddd6fe", "#ede9fe", "#6366f1", "#4f46e5", "#4338ca", "#3730a3",
          "#312e81", "#818cf8", "#a5b4fc", "#c7d2fe", "#e0e7ff", "#eef2ff"]
DEFAULT_INDIGO = ["#6366f1", "#4f46e5", "#4338ca", "#3730a3", "#8b5cf6", "#7c3aed", "#a855f7"]
EMOJI = ["✨", "🚀", "🎯", "⚡", "🔥", "💡", "📈", "🎨", "🛡️", "🌟", "💪", "🎉", "👋", "🙌", "✅",
         "⭐", "🏆"]
METRICS = [r"\b\d+\s*[×x]\s+(faster|better|easier|more\s+(productive|efficient))\b",
           r"\b99\.\d+%\s+uptime\b", r"\bzero[- ]downtime\b"]
FILLER = [r"\bfeature\s+(one|two|three|[123])\b", r"\blorem\s+ipsum\b", r"\bdolor\s+sit\s+amet\b",
          r"\bplaceholder\s+text\b", r"\bsample\s+content\b"]
SANS_DISPLAY = re.compile(
    r"(?:\bh[123]\b|\.h-?(?:hero|xl|lg))[^{}]*\{[^}]*font-family\s*:\s*[\"']?"
    r"(?:Inter|Roboto|Arial|Fraunces|-apple-system|system-ui)", re.I)
LEFT_CARD = re.compile(r"\{[^}]*border-left\s*:\s*\d+px\s+solid[^;]*;[^}]*border-radius\s*:\s*[1-9]"
                       r"|\{[^}]*border-radius\s*:\s*[1-9][^}]*border-left\s*:\s*\d+px\s+solid", re.I)
ROOT_BLOCK = re.compile(r":root\s*\{[^}]*\}|@theme\s*\{[^}]*\}", re.S)


def findings(path, text):
    text = re.sub(r"<!--.*?-->|/\*.*?\*/", "", text, flags=re.S)
    low = text.lower()
    out = []

    def add(sev, rule, why):
        out.append((sev, rule, why))

    grads = re.findall(r"(?:linear|radial|conic)-gradient\([^;]*", low)
    if any(h in g for g in grads for h in PURPLE) or any(re.search(r"\b(purple|violet)\b", g) for g in grads):
        add("P0", "purple-gradient", "a violet/purple gradient")
    elif any(re.search(r"(blue|#3b82f6|#2563eb|#0ea5e9).*(cyan|#06b6d4|#22d3ee)", g) for g in grads):
        add("P0", "trust-gradient", "a blue-to-cyan 'trust' gradient")
    body = ROOT_BLOCK.sub("", low)
    for h in DEFAULT_INDIGO:
        if h in body:
            add("P0", "ai-default-indigo", f"default LLM accent {h} outside the tokens")
            break
    for e in EMOJI:
        if re.search(r"<(?:h[1-6]|button|li|a)\b[^>]*>[^<]*" + re.escape(e), text):
            add("P0", "emoji-icon", f"emoji {e} used as a UI icon")
            break
    if LEFT_CARD.search(text):
        add("P0", "left-accent-card", "rounded card with a coloured left border")
    if SANS_DISPLAY.search(text):
        add("P0", "sans-display", "a heading set in Inter/Roboto/Arial/Fraunces/system sans")
    for pat in METRICS:
        m = re.search(pat, text, re.I)
        if m:
            add("P0", "invented-metric", f'"{m.group(0)}" needs a real source')
            break
    for pat in FILLER:
        m = re.search(pat, text, re.I)
        if m:
            add("P0", "filler-copy", f'"{m.group(0)}"')
            break
    if re.search(r"text-transform\s*:\s*uppercase(?![^}]*letter-spacing)", low):
        add("P1", "all-caps-no-tracking", "uppercase text without letter-spacing")
    if re.search(r"<img\b[^>]*\bsrc\s*=\s*[\"']https?://", low):
        add("P1", "external-image", "a hotlinked image; keep images in the project")
    hexes = re.findall(r"#[0-9a-f]{3,8}\b", body)
    if path.suffix in {".css", ".scss", ".astro", ".vue", ".svelte", ".html"} and len(hexes) > 3:
        add("P1", "raw-hex", f"{len(hexes)} raw hex colours outside :root/@theme; use tokens")
    if len(re.findall(r"var\(--accent\)", body)) > 6:
        add("P1", "accent-overuse", "the accent is used more than a couple of times per screen")
    return out


def main(argv):
    if not argv:
        print(__doc__.strip())
        return 2
    p0 = 0
    for name in argv:
        path = Path(name)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"{name}: unreadable ({exc})")
            continue
        for sev, rule, why in findings(path, text):
            p0 += sev == "P0"
            print(f"{name}: [{sev}] {rule}: {why}")
    print(f"slop_lint: {p0} P0 finding(s)")
    return 1 if p0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
