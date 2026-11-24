# agent-desktop: install, permissions, forms, review notes

Read when the CLI is missing, a permission is denied, a project wants the MCP form, or you need to
know what the kit reviewed. The user-facing docs are at agent-browser.dev/desktop.

## Install (pinned)

The kit reviewed **agent-desktop 1.3.1** (vercel-labs/agent-desktop at `8ffecc1d`, 2026-11-14,
Apache-2.0). Install that version, not `latest`; a newer one goes through `/kit:intake` first,
because the compiled-in guide and the command set change with the version.

```bash
npm install -g agent-desktop@1.3.1       # Node 18+; postinstall fetches the release binary
agent-desktop version                    # {"data":{"version":"1.3.1", ...}}
agent-desktop status
```

What the npm postinstall does (read in the review): downloads
`https://github.com/vercel-labs/agent-desktop/releases/download/v1.3.1/<tarball>` and the release's
`checksums.txt`, compares the SHA-256, extracts exactly the expected entries, and hard-links the
`agent-desktop` bin entry to the native binary so each call skips the Node launcher. The checksum
and the archive come from the same release, so it catches a corrupted download, not a substituted
release; `gh attestation verify <archive> --repo vercel-labs/agent-desktop` proves origin when
that matters. `AGENT_DESKTOP_SKIP_DOWNLOAD=1` skips the download; `AGENT_DESKTOP_BINARY_PATH`
installs a binary you built (`cargo build --release -p agent-desktop`, Rust 1.89).

Alternatives: `brew install agent-desktop` (homebrew-core builds the tagged source; it can lag
npm), or the release archive with its platform helper beside the executable.

Uninstall: `npm uninstall -g agent-desktop`; `rm -r ~/.agent-desktop` removes sessions and traces.

## Permissions

macOS grants Accessibility to the **launching app**, not to the binary: the Terminal, iTerm, the
Claude desktop app, VS Code, or whichever process runs Bash. A thread started from the Claude app
runs under the Claude app's grant. `agent-desktop permissions` reports without prompting;
`permissions --guide` opens System Settings > Privacy & Security > Accessibility (Device Control
and Data Access on macOS 27+) with a panel that shows which app to drag in, and moves on to Screen
Recording if needed. The user confirms with Touch ID or a password. The next CLI call sees the
grant; no restart. Screen Recording is needed only for `screenshot` and `session start
--screenshots`. Automation (System Events) is asked for per command that needs it.

Windows needs no grant at the terminal's integrity level; an elevated app takes input only from
an elevated agent; the binary is unsigned (SmartScreen, Smart App Control). Linux needs Ubuntu
24.04+, `at-spi2-core`, and a shell inside the graphical session (an SSH shell sees no apps).

## CLI or MCP

`agent-desktop mcp` serves every command as an MCP tool over stdio (`desktop_snapshot`,
`desktop_click`, ... about 57 tools). The kit uses the **CLI through Bash**: it costs no context
until a command runs and the compiled-in guide loads only when this skill fires. The MCP form puts
57 tool schemas into every session of a project. Add it to a project's `.mcp.json` only when that
project drives a desktop app in most sessions, and say so in CATALOG.md:

```json
{ "mcpServers": { "agent-desktop": { "command": "agent-desktop", "args": ["mcp"] } } }
```

## State and privacy

Everything the CLI persists is under `~/.agent-desktop` (`AGENT_DESKTOP_HOME` moves it): sessions,
snapshot ref maps, JSONL traces, `latest_snapshot_id`. Traces record commands and results in
event mode; `session start --screenshots` adds pre/post PNGs and ref-map copies, unredacted.
Nothing is sent anywhere: the Rust lockfile has no HTTP client, and the only network code probes
the loopback `--cdp` port it opened. Every local account can reach that port while a `--cdp`
launch runs, so close the app when the web step is over.

## Sandboxes

`agent-desktop sandbox` (1.3.0+) manages a macOS VM provider on Apple Silicon: the first VM is
set up by hand, clones get their own keys, `sandbox exec <name> -- <command>` runs the CLI in the
guest. Upstream calls the first install experimental. The kit did not review it; a project that
wants an isolated desktop for an untrusted app treats it as a separate intake.

## What the review checked (2026-11-17)

Licence Apache-2.0; no hooks, no telemetry, no analytics; `npm/scripts/postinstall.js` and
`npm/bin/agent-desktop` read in full; `Cargo.lock` grepped for HTTP clients (none); the compiled-in
skills (`skills/agent-desktop`, 120 lines plus four references; `skills/agent-desktop-macos`, 58
lines) read; `CONCEPTS.md` for the fail-closed ref resolution, delivery semantics and secure-field
contract. Not checked: the Windows and Linux adapters in practice, the sandbox provider, the
`benchmarks/` claims. On the reviewing Mac the Accessibility grant was denied at review time, so no
live run was recorded; the trial supplies that.
