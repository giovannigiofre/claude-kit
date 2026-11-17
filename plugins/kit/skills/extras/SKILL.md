---
name: extras
description: Offers a kit domain plugin when a task needs one this project lacks - kit-ui for UI or frontend design, a redesign, polish, a design or accessibility audit, or a brand; kit-llm for code that calls an LLM, prompts, tool schemas, evals, prompt tuning or model choice; kit-desktop for a native desktop app to see or operate headless, in a thread too (Electron, Tauri, Swift builds included) - computer use, desktop automation. Use only when kit-ui:*, kit-llm:* or kit-desktop:* skills are missing from your skill list.
---

# Offer a kit domain plugin

The kit keeps its domain skills in separate plugins of the same marketplace, so projects that
never need them don't carry their descriptions:

| Plugin | For | Brings |
|---|---|---|
| `kit-ui` | screens, pages, visual directions and mock-ups from scratch, redesigns, polish, design audits, brands | `kit-ui:ui`, `kit-ui:direction`, `kit-ui:brand` |
| `kit-llm` | code that calls an LLM, prompts, tools, evals, model choice | `kit-llm:llm-build`, `kit-llm:llm-evals`, a hook that spots LLM code on edit |
| `kit-desktop` | a native desktop app to see or operate (macOS, Windows, Linux), headless, from a thread too; a desktop build to check in the app itself | `kit-desktop:desktop` over Vercel Labs' agent-desktop CLI (installed separately, pinned in CATALOG.md) |

1. **Ask once** with AskUserQuestion, header "Kit plugin": "This looks like <UI | LLM | Desktop> work. Use
   Kit <UI | LLM | Desktop> for it?"
   - **Yes, for this project (Recommended):** install it for the project and use it now.
   - **Just this time:** use it now without installing.
   - **No:** go on without it, and don't offer it again in this conversation.

   Without AskUserQuestion (a non-interactive run or a background worker), use it for this task
   without installing and say so in the report.
2. **Use it now.** `claude plugin marketplace list --json` gives the `installLocation` of
   `claude-kit`. Read `<installLocation>/plugins/<plugin>/skills/<skill>/SKILL.md` and follow it;
   its relative links resolve from that folder. When you brief a worker, give it that absolute
   path.
3. **Install it** (on "Yes"): from the repo root, `claude plugin install <plugin>@claude-kit
   --scope project`. It adds the plugin to `enabledPlugins` in `.claude/settings.json`; name that
   file in your report so the user commits it. Until the next session, use the skill by its path (step 2):
   say once "when you're at the Mac: /reload-plugins loads it", and carry on without waiting.
