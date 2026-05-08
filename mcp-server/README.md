# wb-ai-skills MCP server — developer notes

End-user docs (install, usage, env vars, full tools table) live in [`../README.md`](../README.md). This file is for people changing the server itself.

## Run

```bash
cd mcp-server
bun install
bun run src/index.ts          # stdio transport, hangs waiting for the client
bun --watch run src/index.ts  # dev with auto-reload
bunx tsc --noEmit             # typecheck (no tests, no linter)
```

No build step — Bun runs TypeScript directly (`noEmit: true` in `tsconfig.json`).

## Architecture

`src/index.ts` is the single entry point. It builds two singletons (`SshPool` from `lib/ssh.ts`, `Discovery` from `lib/discovery.ts`), packs them into `Ctx` (`src/helpers.ts`), and calls 11 registrars: `registerDiscoveryTools`, `registerSshTools`, `registerJobTools`, `registerMqttTools`, `registerDeviceTools`, `registerConfigTools`, `registerRulesTools`, `registerHistoryTools`, `registerAuditTools`, `registerSerialTools`, `registerDiagnosticTools`. Each lives in `src/tools/<group>.ts` and calls `server.registerTool(name, {description, inputSchema}, handler)`.

### Self-contained `lib/`

- `types.ts` — `Controller`, `ExecResult`, `parseSn`, `defaultHost`, `isUsableAddress`.
- `store.ts` — atomic JSON file at `~/.wb-mcp/controllers.json` for manual entries (no SQLite).
- `discovery.ts` — `avahi-browse -arp` + `dns.lookup`, address merging, IPv6 link-local filtering.
- `ssh.ts` — wrapper over system `ssh`/`sshpass`/`mosquitto_*`/`systemd-run`. `mosquitto_*` runs **on the controller** via SSH, not locally. Uses `shell.ts:shellQuote` everywhere.
- `shell.ts` — `shellQuote(s)` for safe shell composition.
- `audit.ts` — `runAudit`, `runSnapshot`, `runDiffSnapshot`. Section markers use `printf "\n…\n"` so `cat`-ed files without trailing `\n` don't swallow the next section.
- `history-chart.ts` — Vega-Lite renderer; auto-picks single Y-axis / dual Y-axis / normalization-to-[0;1] depending on unit count.

No external runtime deps beyond `@modelcontextprotocol/sdk`, `zod`, `vega`, `vega-lite`. Host needs `ssh`, `sshpass`, `avahi-browse` on `$PATH` — nothing else.

## Conventions for new tools

- **Serial parameter:** `sn: SN` (the `SN` zod schema is exported from `helpers.ts` with description already set).
- **Resolve a controller:** `resolveController(ctx, sn)` — falls back to `defaultHost(sn)` so a fresh SN works without prior discovery.
- **Return:** via `text(data)` (auto-stringifies non-strings) or `err(msg)` (sets `isError: true`). Don't return raw MCP objects.
- **Long shell ops** (`apt`, `docker pull/build`, `wb-release -t/-y`) are detected by `LONG_COMMANDS_RE` in `helpers.ts` — route through `wb_ssh_exec_async`.
- **All shell composition with user-controlled strings** goes through `shellQuote` from `lib/shell.ts`.
- **Tool descriptions and error messages** — in English.
- **MQTT topics** — use `mosquitto_sub -F '%t\t%p'` (TAB separator), names with spaces are common (`Input 0 counter`).
- **Reject invalid wildcards** (`+` inside a level segment) before passing to mosquitto — clear error, not stderr garbage.

## Sync with skills

If you add or rename a tool, update the matching `skills/mcp/<name>/SKILL.md` (routing table). If domain logic changes (new RPC format, Modbus quirk), fix `skills/bash/<name>/SKILL.md` referenced by the mcp variant. The two skill sets are intentionally redundant — they must stay in step or the bash flavor will drift.

## Versioning

`VERSION` at repo root is the single source of truth. The server reads it at startup and reports it in the standard MCP `initialize` handshake (visible in Claude Code under `/mcp` as `wiren-board v<VERSION>`). Master skill `wiren-board` (both flavors) prints the same version. `mcp-server/package.json` is kept in sync manually.
