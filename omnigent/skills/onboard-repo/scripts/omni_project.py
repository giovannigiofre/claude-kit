#!/usr/bin/env python3
"""Register a repo as an Omnigent project and open its first conversation there.

    omni_project.py register NAME WORKSPACE [--handoff FILE] [--title TITLE]

Reuses the project whose workspace is WORKSPACE, if there is one. The project runs the same
agent as the Studio project (this lead). With --handoff, it creates a session in the project
whose first message is FILE's text, and starts the lead's turn on it. Prints JSON:
project_id, session_id.
Stdlib only; talks to the local server (OMNIGENT_URL, default http://127.0.0.1:6767).
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

URL = os.environ.get("OMNIGENT_URL", "http://127.0.0.1:6767").rstrip("/")
HEADERS = {"Origin": "omnigent://internal", "Content-Type": "application/json"}


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def projects():
    d = call("GET", "/v1/projects")
    return d.get("data", d) if isinstance(d, dict) else d


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("name")
    r.add_argument("workspace")
    r.add_argument("--handoff", type=Path)
    r.add_argument("--title", default="Start")
    a = ap.parse_args()

    ws = str(Path(a.workspace).expanduser().resolve())
    if not Path(ws, ".git").exists():
        sys.exit(f"{ws} is not a git checkout")
    ps = projects()
    studio = next((p for p in ps if p.get("name", "").lower() == "studio"), None)
    agent_id = (studio or {}).get("config", {}).get("agent_id") or next(
        (p["config"]["agent_id"] for p in ps if p.get("config", {}).get("agent_id")), None)
    if not agent_id:
        sys.exit("no agent to use: register the Studio project first")
    proj = next((p for p in ps if p.get("config", {}).get("workspace") == ws), None)
    if proj is None:
        proj = call("POST", "/v1/projects", {"name": a.name, "config": {"agent_id": agent_id, "workspace": ws}})
    out = {"project_id": proj["id"], "project": proj["name"], "workspace": ws}
    if a.handoff:
        text = a.handoff.read_text()
        # Without a host the session only stores the message; with one, the runner launches on
        # this Mac and the lead's first turn starts on it.
        hosts = call("GET", "/v1/hosts").get("hosts", [])
        host = next((h for h in hosts if h.get("status") == "online" and h.get("owner") == "local"), None)
        if host is None:
            sys.exit("no online local host: is `omnigent host` running?")
        s = call("POST", "/v1/sessions", {
            "project_id": proj["id"], "host_id": host["host_id"], "title": a.title,
            "initial_items": [{"type": "message", "data": {"role": "user", "content": [
                {"type": "input_text", "text": text}]}}]})
        out["session_id"] = s["id"]
    print(json.dumps(out))


if __name__ == "__main__":
    main()
