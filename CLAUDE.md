# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

End-user overview, install, skill table — see [`README.md`](README.md). This file only carries notes that affect how you should *modify* the repo.

`skills/bash/` — 21 skills with shell recipes. **Source of truth for domain knowledge** (RPC formats, Modbus quirks, wb-rules ES5 limits). All client-side: the LLM uses its built-in `Bash` tool to drive `ssh`, `mosquitto_*`, `avahi-browse`. Nothing runs on the controller.

## Skills

- One directory per skill: `skills/bash/<name>/SKILL.md` with YAML frontmatter (`name`, `description`, `allowed-tools`).
- Editing style: English text, serial `A25NDEMJ` in examples (8 chars).

`./install-skills.sh <claude|opencode> [--global]` is the only supported install path. Manual copy risks drifting away from the opencode frontmatter converter.
