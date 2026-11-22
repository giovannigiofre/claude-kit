#!/usr/bin/env python3
"""Outcome evals for the Omnigent bundle's specialists (engineer, reviewer).

Each case is a real task from a project's history: a brief in the bundle's
format, the commit it starts from, and a grader on the outcome. A run clones
the project into a throwaway directory (never the main checkout), runs the
specialist there with its prompt from `omnigent/agents/<role>/config.yaml`,
grades what it left behind, and deletes the clone.

    run.py list                         cases and their sources
    run.py validate [CASE...]           hidden tests fail on base, pass on the reference
    run.py run [CASE...] [-k 3] [-j 2]  run, grade, write results/<stamp>/
    run.py report RESULTS_DIR           re-print a summary

Stdlib only. See README.md for the case format and the A/B protocol.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE.parent
# Cases come from private repos and stay outside this public one.
DEFAULT_HOME = Path(os.environ.get("OMNIGENT_EVALS_HOME", Path.home() / "Documents/omnigent-research/evals"))
REPOS = {
    "fiscometro": Path.home() / "Documents/repositories/fiscometro",
    "ciaoguest": Path.home() / "Documents/repositories/ciaohost",
}
JUDGE_MODEL = os.environ.get("OMNIGENT_EVALS_JUDGE", "sonnet")
LOCK = threading.Lock()


def log(msg: str) -> None:
    with LOCK:
        print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def sh(cmd, cwd=None, env=None, timeout=None, check=False, input=None) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, input=input, text=True,
                       capture_output=True, shell=isinstance(cmd, str))
    if check and p.returncode:
        raise RuntimeError(f"{cmd!r} failed ({p.returncode}): {p.stderr[-2000:]}")
    return p


# ---------------------------------------------------------------- cases

def load_cases(home: Path, names: list[str]) -> list[dict]:
    out = []
    for cj in sorted(home.glob("cases/*/*/case.json")):
        d = cj.parent
        c = json.loads(cj.read_text())
        c["id"], c["dir"] = d.name, d
        c["brief"] = (d / "brief.md").read_text()
        c["rubric"] = (d / "rubric.md").read_text() if (d / "rubric.md").exists() else ""
        if names and not any(n == c["id"] or n == c["role"] or c["id"].startswith(n) for n in names):
            continue
        out.append(c)
    return out


def role_prompt(role: str, override: str | None) -> str:
    """The specialist's `prompt: |` block, from its config.yaml (or an A/B variant)."""
    path = Path(override) if override else BUNDLE / "agents" / role / "config.yaml"
    text = path.read_text()
    if path.suffix not in (".yaml", ".yml"):
        return text
    lines, block, inside = text.splitlines(), [], False
    for ln in lines:
        if not inside:
            inside = ln.rstrip() == "prompt: |"
            continue
        if ln.strip() and not ln.startswith("  "):
            break
        block.append(ln[2:])
    if not block:
        raise SystemExit(f"no `prompt: |` block in {path}")
    return "\n".join(block).strip() + "\n"


# ---------------------------------------------------------------- sandbox

def clone(case: dict, root: Path) -> Path:
    """A throwaway clone at the case's base, with no way to push or fetch."""
    src = REPOS[case["repo"]]
    wt = root / "repo"
    sh(["git", "clone", "-q", "--shared", "--no-checkout", str(src), str(wt)], check=True)
    g = lambda *a: sh(["git", *a], cwd=wt, check=True)  # noqa: E731
    base = case["base"]
    default = case.get("default_branch", "main")
    g("update-ref", f"refs/remotes/origin/{default}", base)
    g("remote", "set-url", "origin", "file:///nonexistent/eval-sandbox")
    g("checkout", "-q", "-b", case.get("branch", f"eval/{case['id']}"), base)
    seal(wt, {f"refs/heads/{case.get('branch', f'eval/{case["id"]}')}", f"refs/remotes/origin/{default}"})
    if case["role"] == "reviewer":
        build_change(case, wt)
    install(wt)
    return wt


def seal(wt: Path, keep: set[str]) -> None:
    """Only the case's branch and origin/<default> (= base) are left: no later main, branches or tags of the
    project, so the run cannot see how the story ended (a reviewer once found its PR already merged on main)."""
    refs = sh(["git", "for-each-ref", "--format=%(refname)"], cwd=wt, check=True).stdout.split()
    for r in refs:
        if r not in keep:
            sh(["git", "update-ref", "--no-deref", "-d", r], cwd=wt, check=True)
    sh(["git", "reflog", "expire", "--expire=now", "--all"], cwd=wt)


def build_change(case: dict, wt: Path) -> None:
    """The branch under review: the PR's diff, plus the seeded defect if any."""
    diff = sh(["git", "diff", "--binary", case["base"], case["head"]], cwd=wt, check=True).stdout
    sh(["git", "apply", "--index", "--whitespace=nowarn", "-"], cwd=wt, input=diff, check=True)
    seed = case.get("seed")
    if seed:
        sh(["git", "apply", "--index", str(case["dir"] / seed)], cwd=wt, check=True)
    sh(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid", "commit", "-q",
        "-m", case.get("commit_message", case["title"])], cwd=wt, check=True)


def install(wt: Path) -> None:
    if (wt / "pnpm-lock.yaml").exists():
        p = sh("pnpm install --frozen-lockfile --offline", cwd=wt, timeout=900)
        if p.returncode:
            sh("pnpm install --frozen-lockfile", cwd=wt, timeout=900, check=True)


def agent_env(root: Path) -> dict:
    env = dict(os.environ)
    env["OMNIGENT_RUNNER_ID"] = "eval"  # the kit leaves coordinating to lead, as under Omnigent
    ghdir = root / "gh-empty"
    ghdir.mkdir(exist_ok=True)
    env["GH_CONFIG_DIR"] = str(ghdir)  # no gh auth: a run cannot open a PR or comment
    for k in ("GH_TOKEN", "GITHUB_TOKEN"):
        env.pop(k, None)
    return env


# ---------------------------------------------------------------- agent

def run_agent(case: dict, prompt: str, wt: Path, root: Path, out: Path, model: str | None) -> dict:
    brief = case["brief"].replace("{WORKTREE}", str(wt)).replace("{BRANCH}", case.get("branch", f"eval/{case['id']}"))
    (out / "brief.md").write_text(brief)
    cmd = ["claude", "-p", brief, "--append-system-prompt", prompt, "--permission-mode", "auto",
           "--output-format", "stream-json", "--verbose", "--no-session-persistence"]
    if model:
        cmd += ["--model", model]
    t0 = time.time()
    timeout = case.get("timeout_min", 45) * 60
    tr = out / "transcript.jsonl"
    with tr.open("w") as fh:
        try:
            p = subprocess.run(cmd, cwd=wt, env=agent_env(root), stdout=fh, stderr=subprocess.PIPE,
                               text=True, timeout=timeout)
            rc, err = p.returncode, p.stderr[-2000:]
        except subprocess.TimeoutExpired:
            rc, err = "timeout", ""
    res = {}
    for ln in tr.read_text().splitlines():
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            res = ev
    return {"rc": rc, "stderr": err, "seconds": round(time.time() - t0),
            "cost_usd": res.get("total_cost_usd", 0.0), "turns": res.get("num_turns"),
            "report": res.get("result", "")}


# ---------------------------------------------------------------- graders

def judge(task: str, material: str) -> dict:
    schema = {"type": "object", "required": ["verdict", "reason"],
              "properties": {"verdict": {"enum": ["PASS", "FAIL"]}, "reason": {"type": "string"}}}
    prompt = (f"You grade the OUTCOME of an AI agent's task for an eval. Be strict and literal.\n\n"
              f"{task}\n\n{material[:180_000]}\n\nAnswer with verdict PASS or FAIL and a one-paragraph reason.")
    p = sh(["claude", "-p", "--tools", "", "--strict-mcp-config", "--model", JUDGE_MODEL,
            "--output-format", "json", "--no-session-persistence", "--json-schema", json.dumps(schema)],
           input=prompt, timeout=600)
    try:
        d = json.loads(p.stdout)
        so = d.get("structured_output") or json.loads(d.get("result", "{}"))
        return {**so, "cost_usd": d.get("total_cost_usd", 0.0)}
    except (json.JSONDecodeError, TypeError):
        return {"verdict": "FAIL", "reason": f"judge error: {p.stderr[-500:]}", "cost_usd": 0.0}


def worktree_diff(case: dict, wt: Path) -> str:
    sh(["git", "add", "-A", "-N", "."], cwd=wt)
    p = sh(["git", "diff", case["base"], "--", ".", ":(exclude).kit", ":(exclude).claude/evidence",
            ":(exclude)*.log"], cwd=wt)
    return p.stdout


def hidden_tests(case: dict, wt: Path, out: Path) -> dict:
    """Overlay the reference PR's tests on the agent's tree and run them."""
    files = case.get("hidden_tests", [])
    if not files:
        return {"ran": False, "pass": True}
    sh(["git", "checkout", case["ref"], "--", *files, *case.get("hidden_support", [])], cwd=wt, check=True)
    results, ok = [], True
    for f in files:
        pkg = package_dir(wt, f)
        rel = os.path.relpath(wt / f, pkg)
        p = sh(["pnpm", "exec", "vitest", "run", rel], cwd=pkg, timeout=900)
        tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-6:])
        results.append({"file": f, "rc": p.returncode, "tail": tail})
        ok = ok and p.returncode == 0
    (out / "hidden-tests.json").write_text(json.dumps(results, indent=1))
    return {"ran": True, "pass": ok, "files": results}


def package_dir(wt: Path, f: str) -> Path:
    d = (wt / f).parent
    while d != wt and not (d / "package.json").exists():
        d = d.parent
    return d


def grade_engineer(case: dict, wt: Path, run: dict, out: Path) -> dict:
    diff = worktree_diff(case, wt)
    (out / "agent.diff").write_text(diff)
    tests = hidden_tests(case, wt, out)
    if not diff.strip():
        return {"pass": False, "why": "no change", "tests": tests, "judge": None, "judge_cost": 0.0}
    ref = sh(["git", "diff", case["base"], case["ref"], "--", *case.get("judge_paths", ["."])], cwd=wt).stdout
    task = ("The agent was an engineer given this brief:\n<brief>\n" + case["brief"] + "\n</brief>\n\n"
            "Grading rubric (from the owner's real PR; the reference diff is ONE correct solution, "
            "not the only one):\n<rubric>\n" + case["rubric"] + "\n</rubric>\n\n"
            "PASS only if the agent's change meets every DONE WHEN point and the rubric, stays in SCOPE, "
            "and the agent's report does not claim checks it did not run. Style differences from the "
            "reference are fine.")
    material = (f"<agent_report>\n{run['report'][:20000]}\n</agent_report>\n\n"
                f"<hidden_tests passed={tests['pass']}>\n{json.dumps(tests.get('files', []))[:6000]}\n</hidden_tests>\n\n"
                f"<agent_diff>\n{diff[:90000]}\n</agent_diff>\n\n<reference_diff>\n{ref[:60000]}\n</reference_diff>")
    j = judge(task, material)
    return {"pass": bool(tests["pass"] and j["verdict"] == "PASS"), "tests": tests, "judge": j,
            "judge_cost": j.get("cost_usd", 0.0)}


VERDICT = re.compile(r"VERDICT\W{0,6}(PASS|FAIL|CANNOT_VERIFY)", re.I)


def grade_reviewer(case: dict, wt: Path, run: dict, out: Path) -> dict:
    m = VERDICT.findall(run["report"] or "")
    verdict = m[-1].upper() if m else "NONE"
    expect = case["expect"]
    # Editing the change = new commits on the branch under review. A dirty tree is recorded, not failed:
    # a build or a formatter run by the gate can touch tracked files without the reviewer meaning to edit.
    branch_sha = sh(["git", "rev-parse", f"refs/heads/{case['branch']}"], cwd=wt).stdout.strip()
    edited = branch_sha != case.get("_head_sha")
    (out / "tree-after.txt").write_text(sh(["git", "status", "--porcelain"], cwd=wt).stdout)
    if verdict != expect or edited:
        why = "edited the change" if edited else f"verdict {verdict}, expected {expect}"
        return {"pass": False, "verdict": verdict, "edited": edited, "why": why, "judge": None, "judge_cost": 0.0}
    if expect == "PASS":
        return {"pass": True, "verdict": verdict, "edited": False, "judge": None, "judge_cost": 0.0}
    task = ("A code reviewer agent reviewed a branch that contains a known defect. The defect:\n<defect>\n"
            + case["rubric"] + "\n</defect>\n\nPASS only if the reviewer's PROBLEMS section names this "
            "defect specifically (the place, file or behaviour, and why it is wrong). A vague concern, a "
            "different problem, or the defect listed only under QUESTIONS is FAIL.")
    j = judge(task, f"<review_report>\n{run['report'][:30000]}\n</review_report>")
    return {"pass": j["verdict"] == "PASS", "verdict": verdict, "edited": False, "judge": j,
            "judge_cost": j.get("cost_usd", 0.0)}


# ---------------------------------------------------------------- run

def one_run(case: dict, n: int, prompt: str, outdir: Path, args) -> dict:
    out = outdir / "runs" / case["id"] / str(n)
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"omni-eval-{case['id'][:20]}-", dir=args.tmp))
    rec = {"case": case["id"], "role": case["role"], "run": n}
    try:
        log(f"{case['id']}#{n}: clone")
        wt = clone(case, root)
        case = {**case, "_head_sha": sh(["git", "rev-parse", "HEAD"], cwd=wt).stdout.strip()}
        log(f"{case['id']}#{n}: agent")
        run = run_agent(case, prompt, wt, root, out, args.model)
        log(f"{case['id']}#{n}: grade ({run['seconds']}s, ${run['cost_usd']:.2f})")
        g = (grade_engineer if case["role"] == "engineer" else grade_reviewer)(case, wt, run, out)
        rec.update(run=n, seconds=run["seconds"], cost_usd=run["cost_usd"], turns=run["turns"],
                   rc=run["rc"], grade=g, passed=g["pass"])
        (out / "report.md").write_text(run["report"] or "")
    except Exception as e:  # noqa: BLE001 - a broken run is a recorded failure, not a crash
        rec.update(passed=False, error=str(e)[-2000:], seconds=0, cost_usd=0.0)
    finally:
        if args.keep:
            rec["kept"] = str(root)
        else:
            shutil.rmtree(root, ignore_errors=True)
    (out / "grade.json").write_text(json.dumps(rec, indent=1, default=str))
    log(f"{case['id']}#{n}: {'PASS' if rec['passed'] else 'FAIL'} {rec.get('error', '')[:200]}")
    return rec


def summarize(recs: list[dict], meta: dict) -> dict:
    by: dict[str, list[dict]] = {}
    for r in recs:
        by.setdefault(r["case"], []).append(r)
    cases = {}
    for cid, rs in sorted(by.items()):
        k = len(rs)
        p = sum(r["passed"] for r in rs)
        cases[cid] = {"role": rs[0]["role"], "k": k, "passes": p, "pass_at_1": round(p / k, 3),
                      "pass_hat_k": p == k, "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rs), 2),
                      "judge_cost_usd": round(sum((r.get("grade") or {}).get("judge_cost", 0) for r in rs), 2),
                      "minutes": round(sum(r.get("seconds") or 0 for r in rs) / 60, 1)}
    roles = {}
    for role in sorted({c["role"] for c in cases.values()}):
        cs = [c for c in cases.values() if c["role"] == role]
        roles[role] = {"cases": len(cs), "pass_at_1": round(sum(c["pass_at_1"] for c in cs) / len(cs), 3),
                       "pass_hat_k": round(sum(c["pass_hat_k"] for c in cs) / len(cs), 3),
                       "cost_usd": round(sum(c["cost_usd"] + c["judge_cost_usd"] for c in cs), 2),
                       "agent_minutes": round(sum(c["minutes"] for c in cs), 1)}
    return {**meta, "roles": roles, "cases": cases}


def write_summary(outdir: Path, s: dict) -> None:
    (outdir / "summary.json").write_text(json.dumps(s, indent=1))
    lines = [f"# Eval run {s['stamp']}", "",
             f"variant: {s['variant']} · model: {s['model'] or 'default'} · k={s['k']} · wall {s['wall_minutes']} min", "",
             "| role | cases | pass@1 | pass^k | cost $ | agent min |", "|---|---|---|---|---|---|"]
    for role, r in s["roles"].items():
        lines.append(f"| {role} | {r['cases']} | {r['pass_at_1']:.2f} | {r['pass_hat_k']:.2f} | {r['cost_usd']} | {r['agent_minutes']} |")
    lines += ["", "| case | role | passes | pass^k | cost $ | min |", "|---|---|---|---|---|---|"]
    for cid, c in s["cases"].items():
        lines.append(f"| {cid} | {c['role']} | {c['passes']}/{c['k']} | {'yes' if c['pass_hat_k'] else 'no'} | {c['cost_usd']} | {c['minutes']} |")
    (outdir / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def cmd_run(args) -> None:
    cases = load_cases(args.home, args.cases)
    if not cases:
        raise SystemExit("no cases match")
    stamp = dt.datetime.now().strftime("%Y-%m-%dT%H-%M")
    variant = args.variant or "baseline"
    outdir = args.home / "results" / f"{stamp}-{variant}"
    outdir.mkdir(parents=True, exist_ok=True)
    prompts = {role: role_prompt(role, getattr(args, f"{role}_prompt")) for role in {c["role"] for c in cases}}
    for role, p in prompts.items():
        (outdir / f"prompt-{role}.md").write_text(p)
    t0 = time.time()
    jobs = [(c, n) for c in cases for n in range(1, args.k + 1)]
    with cf.ThreadPoolExecutor(args.jobs) as ex:
        recs = list(ex.map(lambda cn: one_run(cn[0], cn[1], prompts[cn[0]["role"]], outdir, args), jobs))
    meta = {"stamp": stamp, "variant": variant, "model": args.model, "k": args.k,
            "wall_minutes": round((time.time() - t0) / 60, 1),
            "claude_version": sh(["claude", "--version"]).stdout.strip()}
    write_summary(outdir, summarize(recs, meta))
    print(f"\nresults: {outdir}")


def cmd_validate(args) -> None:
    """Engineer: hidden tests must fail on base and pass on the reference. Reviewer: the branch builds."""
    bad = 0
    for c in load_cases(args.home, args.cases):
        root = Path(tempfile.mkdtemp(prefix="omni-validate-", dir=args.tmp))
        try:
            wt = clone(c, root)
            if c["role"] == "engineer":
                files = c.get("hidden_tests", [])
                red = hidden_tests(c, wt, root)
                sh(["git", "checkout", c["ref"], "--", "."], cwd=wt, check=True)
                green = hidden_tests(c, wt, root)
                ok = (not files or not red["pass"]) and green["pass"]
                msg = f"base {'red' if not red['pass'] else 'GREEN?'} / ref {'green' if green['pass'] else 'RED?'}"
            else:
                ok, msg = True, "branch built"
        except Exception as e:  # noqa: BLE001
            ok, msg = False, str(e)[-300:]
        finally:
            shutil.rmtree(root, ignore_errors=True)
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {c['id']}: {msg}", flush=True)
    sys.exit(1 if bad else 0)


def cmd_list(args) -> None:
    for c in load_cases(args.home, args.cases):
        extra = c.get("expect", "") if c["role"] == "reviewer" else f"{len(c.get('hidden_tests', []))} hidden test files"
        print(f"{c['role']:9} {c['id']:40} {c.get('source', ''):16} {extra}  {c.get('pr', '')}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", type=Path, default=DEFAULT_HOME, help="folder with cases/ and results/")
    ap.add_argument("--tmp", default=None, help="where throwaway clones go (default: system temp)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "validate", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("cases", nargs="*", help="case ids, id prefixes, or a role")
        if name == "run":
            sp.add_argument("-k", type=int, default=3, help="runs per case (pass^k)")
            sp.add_argument("-j", "--jobs", type=int, default=2, help="runs in parallel")
            sp.add_argument("--model", default=None, help="model for the specialist (default: Claude Code's)")
            sp.add_argument("--variant", default=None, help="label for an A/B arm")
            sp.add_argument("--engineer-prompt", default=None, help="config.yaml or .md to use instead of the bundle's")
            sp.add_argument("--reviewer-prompt", default=None)
            sp.add_argument("--keep", action="store_true", help="keep the throwaway clones")
    rp = sub.add_parser("report")
    rp.add_argument("dir", type=Path)
    args = ap.parse_args()
    if args.cmd == "report":
        print((args.dir / "summary.md").read_text())
        return
    {"list": cmd_list, "validate": cmd_validate, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
