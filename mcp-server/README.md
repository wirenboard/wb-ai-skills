# wb-ai-skills MCP server

MCP server exposing 43 typed tools for managing [Wiren Board](https://wirenboard.com) controllers from any [MCP](https://modelcontextprotocol.io)-aware client (tested: [Claude Code](https://claude.ai/code), [opencode](https://opencode.ai)).

This is the implementation reference. For end-user installation and concepts see the [main README](../README.md) and [INSTALL.md](../INSTALL.md).

## Run

```bash
cd mcp-server
bun install
bun run src/index.ts          # stdio transport, hangs waiting for the client
bun --watch run src/index.ts  # dev with auto-reload
```

No build step — Bun runs TypeScript directly (`noEmit: true` in `tsconfig.json`). No tests, no linter — typecheck via `bunx tsc --noEmit`.

Connect via `.mcp.json` / `~/.claude.json` / `opencode.json` — see [INSTALL.md §4](../INSTALL.md#4-connect-the-mcp-server).

## Tools (43)

### Discovery (3)

| Tool | Purpose |
|---|---|
| `wb_discover` | List controllers seen via mDNS + manual entries |
| `wb_probe` | Reachability + uname/release/fwVersion/uptime for one SN |
| `wb_add_controller` | Manually register by hostname/IP (when mDNS is blocked) |

### SSH & files (4)

| Tool | Purpose |
|---|---|
| `wb_ssh_exec` | Synchronous shell command, up to 2 min |
| `wb_ssh_exec_async` | Background task via `systemd-run --collect`, survives SSH disconnect |
| `wb_read_file` | Read up to 64 KB |
| `wb_write_file` | Write via SFTP, any size |

### Async jobs (3)

| Tool | Purpose |
|---|---|
| `wb_job_status` | Active state, exit code, log line count, label |
| `wb_job_tail` | Incremental log reader (`fromLine`/`maxLines`) |
| `wb_job_cancel` | SIGTERM the unit |

Job script and log live in `/mnt/data/ai/wb-ai-skills/jobs/<id>.{sh,log}`. Logs are written via systemd `StandardOutput=append:` (no shell redirect, no quoting hazards). 24-hour TTL gc on each `jobStart`.

### MQTT (4)

| Tool | Purpose |
|---|---|
| `wb_mqtt_read` | Read one retained topic (any, not only WB) |
| `wb_mqtt_write` | Publish to any topic; optional `retain`/`qos` |
| `wb_mqtt_list` | Subscribe by prefix for `timeout` seconds and collect topic→payload pairs |
| `wb_mqtt_rpc` | One-shot RPC over MQTT (wb-mqtt-serial, confed, wbrules, db_logger, wb-device-manager, ...) |

`wb_mqtt_list` and `wb_mqtt_read` raise a clear error on invalid wildcard topics (e.g. `+` inside a level segment).

### MQTT devices (3)

| Tool | Purpose |
|---|---|
| `wb_mqtt_devices` | Compact `{id: human-name}` map |
| `wb_mqtt_controls` | Raw topic→payload list for one device |
| `wb_mqtt_inventory` | **Combined view**: devices + driver + parsed error + controls with unpacked meta (value, type, units, readonly, order, min/max, error). One call instead of N+1. Filter by `device` substring. Error flags follow [WB Conventions](https://github.com/wirenboard/conventions): `r` / `w` / `p` and combinations |

### Confed (2)

| Tool | Purpose |
|---|---|
| `wb_confed_load` | Load `/etc/wb-mqtt-serial.conf`, `/etc/wb-hardware.conf`, etc. with schema |
| `wb_confed_save` | Save with validation + atomic service restart. Accepts `content` as object **or** JSON-string (auto-parses) |

### wb-rules (5)

| Tool | Purpose |
|---|---|
| `wb_rules_list` | All rule files with enabled/disabled state and the rules each defines |
| `wb_rules_load` | Read one rule's source |
| `wb_rules_save` | Save (JS validated by the engine, hot reload) |
| `wb_rules_disable` | Rename `<name>.js` → `<name>.js.disabled` (reversible) |
| `wb_rules_delete` | `Editor/Remove` (irreversible — confirm with the user) |

### History (2)

| Tool | Purpose |
|---|---|
| `wb_history` | Query `db_logger/history/get_values`: points + min/max/avg per channel |
| `wb_history_chart` | Render Vega-Lite SVG. Types: line, bar, area, point, histogram, heatmap, boxplot. Auto picks 1-unit / 2-unit dual-Y-axis / 3+ unit normalization-to-[0;1]. Returns inline SVG or writes to `outputPath` (large charts) |

### Audit & state (3)

| Tool | Purpose |
|---|---|
| `wb_audit` | Packages, services, cron, opt/usr-local, symlinks, /mnt/data dirs, dpkg-modified files. `release` parsed into `{name, suite, target, repoPrefix}` |
| `wb_state_save` | JSON snapshot to `/mnt/data/ai/wb-ai-skills/snapshots/snapshot-<ts>.json` |
| `wb_state_diff` | Compare a saved snapshot to current state — added/removed packages/units/opt |

### Modbus / wb-mqtt-serial (7)

| Tool | Purpose |
|---|---|
| `wb_modbus_templates_list` | Templates from `wb-mqtt-serial/config/Load.types`. Without `filter` — group summary; with `filter` — flat list of matched entries |
| `wb_modbus_template` | One template's content (channels, parameters, groups, translations). By `device_type` or `mqtt-id`, case-insensitive. Views: `summary` (default, compact channel list), `full`, `channels-only`, `meta-only`. Filters: `enabledOnly`, `channelFilter` |
| `wb_modbus_device_info` | Firmware parameters (fw, model, debounce/modes/mappings). NOT a channel list |
| `wb_modbus_probe` | Quick ping for one slave on a port |
| `wb_modbus_ports` | RS-485 port parameters from the driver config |
| `wb_modbus_scan` | Bus scan via `wb-device-manager/bus-scan/Start` (async, polls retained `/wb-device-manager/state`). Default `scan_type="extended"` (Fast Modbus, seconds); `"standard"` for third-party. Auto-detects ports and baud (115200, 9600) |
| `wb_modbus_add_devices` | Add discovered devices to the wb-mqtt-serial config. Reads `/wb-device-manager/state`, resolves `signature → device_type` via RPC, reads each template, copies parameter defaults into the device record (otherwise schema validation rejects required params like WB-MAI6 `in1_type..in6_type`). Has `dryRun=true` for preview |

### Diagnostics (7)

| Tool | Purpose |
|---|---|
| `wb_metrics` | Load avg, RAM, disk free for `/` and `/mnt/data` |
| `wb_logs` | `journalctl` wrapper with `since`/`until`/`grep`/`grepInvert`/`priority`/`unit`/`lines` |
| `wb_failed` | `systemctl --failed` |
| `wb_serial_debug` | Atomic enable→capture→disable cycle for `wb-mqtt-serial` debug=true; `trap`-protected |
| `wb_systemd_unit` | Manage and inspect a unit. Actions: `status` (parsed), `start`/`stop`/`restart`/`reload`/`enable`/`disable`/`mask`/`unmask`/`cat`/`list-deps` |
| `wb_network_status` | Interfaces (`ip -j`) + NetworkManager connections + default route + optional ping |
| `wb_cloud_status` | wb-cloud-agent: service activity, certificate presence, providers, MQTT controls (`status`, `activation_link`, `cloud_base_url`) |

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WB_SSH_USER` | `root` | SSH login |
| `WB_SSH_PASSWORD` | `wirenboard` | SSH password (used only if `WB_SSH_KEY` is unset) |
| `WB_SSH_KEY` | — | Path to private key (preferred) |
| `WB_DISCOVERY_INTERVAL` | `15000` | mDNS scan period in ms |

## Architecture

`src/index.ts` is the single entry point. It builds two singletons (`SshPool` from `lib/ssh.ts`, `Discovery` from `lib/discovery.ts`), packs them into `Ctx` (`src/helpers.ts`), and calls 11 registrars: `registerDiscoveryTools`, `registerSshTools`, `registerJobTools`, `registerMqttTools`, `registerDeviceTools`, `registerConfigTools`, `registerRulesTools`, `registerHistoryTools`, `registerAuditTools`, `registerSerialTools`, `registerDiagnosticTools`. Each lives in `src/tools/<group>.ts` and calls `server.registerTool(name, {description, inputSchema}, handler)`.

### Self-contained `lib/`

- `types.ts` — `Controller`, `ExecResult`, `parseSn`, `defaultHost`, `isUsableAddress`.
- `store.ts` — atomic JSON file at `~/.wb-mcp/controllers.json` for manual entries (no SQLite).
- `discovery.ts` — `avahi-browse -arp` + `dns.lookup`, address merging, IPv6 link-local filtering.
- `ssh.ts` — wrapper over system `ssh`/`sshpass`/`mosquitto_*`/`systemd-run`. Uses `shell.ts:shellQuote` everywhere.
- `shell.ts` — `shellQuote(s)` for safe shell composition.
- `audit.ts` — `runAudit`, `runSnapshot`, `runDiffSnapshot`. `release` parsed into a structured object.
- `history-chart.ts` — Vega-Lite renderer.

No external runtime deps beyond `@modelcontextprotocol/sdk`, `zod`, `vega`, `vega-lite`. Host needs `ssh`, `sshpass`, `avahi-browse`, `mosquitto_sub`/`pub` available on `$PATH`. Controllers need only stock sshd + mosquitto.

### Conventions for new tools

- Serial parameter: `sn: SN` (the `SN` zod schema is exported from `helpers.ts`).
- Resolve a `Controller`: `resolveController(ctx, sn)` — falls back to `defaultHost(sn)` so a fresh SN works without prior discovery.
- Return via `text(data)` (auto-stringifies non-strings) or `err(msg)` (sets `isError: true`). Don't return raw MCP objects.
- For long-running shell ops (`apt`, `docker pull/build`, `wb-release -t/-y`) detected by `LONG_COMMANDS_RE` — route through `wb_ssh_exec_async`.
- All shell composition with user-controlled strings goes through `shellQuote` from `lib/shell.ts`.
- Tool descriptions and error messages — in English (this convention is also stated in the project's `CLAUDE.md`).

### Sync with skills

If you add or rename a tool, update the routing tables in `skills/mcp/<name>/SKILL.md` (and the matching bash variant if it teaches the underlying RPC). The two skill sets are intentionally redundant — they must stay in step or the bash flavor will drift.

## License

MIT (see [`../LICENSE`](../LICENSE)).
