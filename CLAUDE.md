# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

End-user overview, install, tool/skill tables, env vars — see [`README.md`](README.md). Server-internal architecture and conventions for new MCP tools — [`mcp-server/README.md`](mcp-server/README.md). This file only carries notes that affect how you should *modify* the repo.

Three parts:

- `mcp-server/` — TypeScript MCP server on Bun. 43 typed tools.
- `skills/bash/` — 21 skills with shell recipes. **Source of truth for domain knowledge** (RPC formats, Modbus quirks, wb-rules ES5 limits).
- `skills/mcp/` — 19 thin skills routing intents to `wb_*` tools. Reference bash counterparts for deep details, don't duplicate.

All client-side. Nothing runs on the controller.

## Skills

- One directory per skill: `skills/<flavor>/<name>/SKILL.md` with YAML frontmatter (`name`, `description`, `allowed-tools`).
- Same `name:` in both flavors — the user enables exactly one.
- MCP variants ~30-50 lines: intent → tool table + link to bash. Bash variants hold the full domain logic (`wb-rules` is the largest at ~635 lines).
- Editing style: English text, serial `A25NDEMJ` in examples (8 chars).

`./install-skills.sh <bash|mcp> <claude|opencode> [--global]` is the only supported install path. Manual copy risks drifting away from the opencode frontmatter converter.

For mcp flavor the installer also pulls `wb-diagrams` and `wb-documentation-search` from `skills/bash/` (controller-independent — MCP would add no value there).

## Consistency between server and skills

- Add/rename a tool in `mcp-server/src/tools/<group>.ts` → update routing table in `skills/mcp/<name>/SKILL.md`.
- Domain change (new RPC, new Modbus template) → fix `skills/bash/<name>/SKILL.md` referenced by the mcp variant.
- Otherwise the two flavors will drift.

## Server conventions

See [`mcp-server/README.md`](mcp-server/README.md) for `Ctx` / `resolveController` / `text` / `err` / `shellQuote` / `LONG_COMMANDS_RE`. Don't duplicate those rules here.
