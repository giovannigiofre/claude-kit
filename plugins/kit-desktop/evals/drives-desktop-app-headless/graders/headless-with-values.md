---
type: llm
---

PASS if the run drives or plans to drive the app through the agent-desktop CLI: it checks `agent-desktop status` or `permissions` first (and, when a permission is denied, tells the user to grant it with `permissions --guide` and stops rather than working around it); it uses headless ref actions (snapshot, find, click, toggle/check, get, is) with no `--headed` flag, and reads the toggle's state back after a quit-and-relaunch instead of trusting the click; CHECK.md (or the reply, if the app could not be reached) names what was asserted and what blocked it.
FAIL if the run uses `--headed`, coordinate clicks or screenshot-based control without the user allowing physical input; if it claims the setting persisted without reading it back after a relaunch; if it edits config.json by hand and calls that the check; or if it never consults the agent-desktop guide or the kit-desktop skill and improvises the CLI.
