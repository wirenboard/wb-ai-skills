# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Integration of Claude Code and opencode with [Wiren Board](https://wirenboard.com) controllers. Three parts:

- `mcp-server/` — MCP server (TypeScript on Bun) with 43 typed tools for controlling WB over SSH/MQTT.
- `skills/bash/` — 21 skills with Bash recipes (SSH + `mosquitto_*` + `avahi-browse`), work without MCP.
- `skills/mcp/` — 19 thin skills routing intents to `wb_*` tools of the MCP server.

All parts are client-side: the target controller is always remote (`ssh root@wirenboard-<SN>.local`, password `wirenboard` by default). This repository contains no code that runs *on* the controller.

`skills/bash/` is the source of domain knowledge (wb-rules syntax, RPC formats, Modbus gotchas). MCP variants reference bash for deep details and don't duplicate them. The same `name:` in frontmatter applies to both sets; the user enables exactly one.

## mcp-server — commands

```bash
cd mcp-server
bun install
bun run src/index.ts        # run (via stdio transport)
bun --watch run src/index.ts # dev with auto-restart
```

No tests, no linter. No build step — Bun executes TypeScript directly (`noEmit: true` in `tsconfig.json`).

Connecting to Claude Code — via `.mcp.json` (see `mcp-server/.mcp.json.example`) or `claude mcp add wiren-board -- bun run /abs/path/mcp-server/src/index.ts`.

## mcp-server — architecture

`src/index.ts` is the single entry point. Creates two singleton objects (`SshPool` from `lib/ssh.ts`, `Discovery` from `lib/discovery.ts`), packs them into `Ctx` (see `src/helpers.ts:5`) and sequentially calls 11 registrars: `registerDiscoveryTools`, `registerSshTools`, `registerJobTools`, `registerMqttTools`, `registerDeviceTools`, `registerConfigTools`, `registerRulesTools`, `registerHistoryTools`, `registerAuditTools`, `registerSerialTools`, `registerDiagnosticTools`. Each registrar lives in `src/tools/<group>.ts` and adds tools to `McpServer` via `server.registerTool(name, {description, inputSchema}, handler)`.

**Self-contained implementation in `mcp-server/src/lib/`:**
- `types.ts` — `Controller`, `ExecResult`, `parseSn`, `defaultHost`, `isUsableAddress`.
- `store.ts` — JSON file `~/.wb-mcp/controllers.json` for manual controllers (no SQLite).
- `discovery.ts` — `avahi-browse -arp` + `dns.lookup`, address merging, IPv6 link-local filtering.
- `ssh.ts` — wrapper over system `ssh`/`sshpass`/`mosquitto_*`/`systemd-run` (no npm bindings).
- `audit.ts` — `runAudit`, `runSnapshot`, `runDiffSnapshot` for wb_audit/state-tools.

No external dependencies except `@modelcontextprotocol/sdk`, `zod` and `@types/bun`. Binaries `ssh`, `sshpass`, `avahi-browse`, `mosquitto_sub`/`mosquitto_pub` are needed on the host where the MCP server runs (any Linux). The controller needs nothing — only stock sshd and mosquitto.

**Conventions for new tools:**

- Serial parameter: `sn: SN` from `helpers.ts` (zod schema, description already set).
- Get controller by SN: `resolveController(ctx, sn)` — throws a clear error if not found.
- Return result via `text(data)` (string or JSON will be serialized) or `err(msg)` for an error. Don't return raw MCP objects.
- Long operations (`apt`, `docker run/pull/build`, `wb-release -t/-y`) are detected by the `LONG_COMMANDS_RE` regex in `helpers.ts:27` — used for routing into background tasks (`wb_ssh_exec_async`).
- Tool descriptions and error messages — in English (matches existing style).

43 tools in 11 groups: discovery (3) · ssh+files (4) · jobs (3) · mqtt (4) · mqtt-devices (3) · confed (2) · wb-rules (5) · history (2) · audit/state (3) · modbus/serial (7) · diagnostics (7). Full table — in `mcp-server/README.md`.

## mcp-server environment variables

| Variable | Default | Purpose |
|------------|---------|------------|
| `WB_SSH_USER` | `root` | SSH login |
| `WB_SSH_PASSWORD` | `wirenboard` | SSH password |
| `WB_SSH_KEY` | — | path to private key (alternative to password) |
| `WB_DISCOVERY_INTERVAL` | `15000` | mDNS scan period, ms |
| `WB_CHART_FORMAT` | — | `svg` forces wb_history_chart to write an SVG file instead of Mermaid (for TUI clients). Unset / `mermaid` / `auto` — Mermaid (default). |

## skills — structure

Each skill is a directory `skills/<flavor>/<name>/SKILL.md` with YAML frontmatter (`name`, `description`, `allowed-tools`). `flavor` is `bash` or `mcp`. The root `wiren-board` is the master skill, its description asks to load it for any work with WB. Names inside are the same in both sets: the same `/wb-rules` means either the bash or mcp variant — depending on which set is enabled.

**Installation** — via `./install-skills.sh <bash|mcp> <claude|opencode> [--global]`. For Claude Code — symlinks to directories. For opencode — frontmatter conversion (`name` becomes the file name, `allowed-tools` is dropped, `mode: primary` is added) and flat `.md` files in `.opencode/agents/`. The script is the only supported installation method; manual copying risks drifting away from the converter.

Skills in `bash/` — 21, in `mcp/` — 19 (no `wb-diagrams` and `wb-documentation-search`: they don't depend on the controller, MCP adds no value — the user takes them from `bash/` regardless of whether MCP is present).

When editing skills keep the existing style: English-language descriptions, serial `A25NDEMJ` (8 characters). MCP variants are short (~30-50 lines), with an "intent → tool" table and a link to the bash counterpart. Bash variants contain the full domain logic; the largest is `wb-rules/SKILL.md` (635 lines, ES5 subset, `defineRule`, virtual devices).

## Consistency between mcp-server and skills

When adding a new MCP tool to `mcp-server/src/tools/<group>.ts` update the corresponding `skills/mcp/<name>/SKILL.md` (routing table). If the domain logic changes (new RPC format, new Modbus template) — fix the `skills/bash/<name>/SKILL.md` referenced by the mcp variant. Otherwise the sets will drift apart.
