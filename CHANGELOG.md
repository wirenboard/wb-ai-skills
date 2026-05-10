# CHANGELOG

Format — [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning — [SemVer](https://semver.org/).

## [Unreleased]

### Removed

- **MCP server** (`mcp-server/`) and the **mcp-flavor skills** (`skills/mcp/`, 19 skills). Repository now ships only the bash flavor (21 skills under `skills/bash/`); the LLM drives controllers via its built-in `Bash` tool. The MCP implementation stays in git history for reference while a Python `wb-cli` replacement is being built.
- `install-skills.sh` no longer takes a `flavor` argument: `./install-skills.sh <claude|opencode> [--global]`.

## [0.1.0] — 2026-05-08

First public release. Tested on A25NDEMJ (wb7, wb-2410/wb-2602) and A2V6W7I6 (wb8, wb-2507).

### Versioning

- Single source of truth — root `VERSION` file. The MCP server reads it at
  startup and reports it in the standard MCP `initialize` handshake (visible
  in Claude Code under `/mcp` as `wiren-board v<VERSION>`). Master skill
  `wiren-board` (both bash and mcp flavors) prints the same version in its
  header. `mcp-server/package.json` is kept in sync manually.

### MCP server

**43 typed tools in 11 groups**, implemented via standard MCP (`@modelcontextprotocol/sdk`) on Bun:

- **Discovery (3):** `wb_discover` (mDNS + manual), `wb_probe`, `wb_add_controller`.
- **SSH+files (4):** `wb_ssh_exec`, `wb_ssh_exec_async`, `wb_read_file`, `wb_write_file`.
- **Async jobs (3):** `wb_job_status`, `wb_job_tail`, `wb_job_cancel`. Via `systemd-run --collect` + script-file (`/mnt/data/ai/wb-ai-skills/jobs/<id>.sh`) + `StandardOutput=append:`. Survives SSH disconnect, gc by 24-hour TTL.
- **MQTT (4):** `wb_mqtt_read` (any topic, not only WB), `wb_mqtt_write` (with optional `retain`/`qos`), `wb_mqtt_list`, `wb_mqtt_rpc`.
- **MQTT devices (3):** `wb_mqtt_devices`, `wb_mqtt_controls`, `wb_mqtt_inventory` — combined: id+driver+error+controls with unpacked meta and error flags per [WB Conventions](https://github.com/wirenboard/conventions) (`r`/`w`/`p`).
- **Confed (2):** `wb_confed_load`, `wb_confed_save`. Accepts content as object **or** JSON string (auto-parses — otherwise confed will write an escape-quoted string and break the config).
- **wb-rules (5):** `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_disable` (via `Editor/ChangeState`), `wb_rules_delete` (via `Editor/Remove`).
- **History (2):** `wb_history`, `wb_history_chart` — Vega-Lite SVG (line/bar/area/point/histogram/heatmap/boxplot) with 1/2/3+ unit strategies (single scale / dual Y-axis / normalization to [0;1]).
- **Audit/state (3):** `wb_audit` (release parsed into an object), `wb_state_save`, `wb_state_diff`.
- **Modbus/serial (6):** `wb_modbus_template` (via RPC `config/Load.types` → mqtt-id → template file; `view=summary/full/channels-only/meta-only`, `enabledOnly`, `channelFilter`), `wb_modbus_templates_list` (without filter — group summary, with filter — flat list, case-insensitive), `wb_modbus_device_info` (firmware parameters fw/model/parameters), `wb_modbus_probe`, `wb_modbus_ports`, `wb_modbus_scan` (via `wb-device-manager/bus-scan/Start`, async, extended Fast Modbus + standard fallback; auto-detect ports and baud), `wb_modbus_add_devices` (auto-add discovered by scanner with `dryRun`).
- **Diagnostics (7):** `wb_metrics`, `wb_logs` (with `since`/`until`/`grep`/`grepInvert`), `wb_failed`, `wb_serial_debug` (atomic enable→collect→disable via `trap restore_off`), `wb_systemd_unit` (status/start/stop/restart/enable/disable/mask/unmask/cat/list-deps), `wb_network_status` (interfaces+nm+ping), `wb_cloud_status` (service+cert+MQTT-controls).

### Skills

**21 bash skills** + **19 mcp skills**:
- Common domain stack: `wiren-board`, `wb-mqtt-serial`, `wb-serial-templates`, `wb-rules`, `wb-scenarios`, `wb-notifications`, `wb-troubleshooting`, `wb-troubleshooting-serial`, `wb-services`, `wb-network`, `wb-cloud`, `wb-mqtt-broker`, `wb-controller-backup`, `wb-controller-update`, `wb-hardware-modules`, `wb-software-install`, `wb-zigbee`, `wb-history`, `wb-bugreport`.
- Bash-only (controller-independent): `wb-diagrams` (Mermaid), `wb-documentation-search` (search across wiki/GitHub).
- Compatible with Claude Code and opencode (via `install-skills.sh`).

### Architectural decisions

- **SSH host-key:** `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null` — survives factory reset and FIT firmware reflash without `ssh-keygen -R`.
- **No external SQLite/npm bindings:** the MCP server uses only `@modelcontextprotocol/sdk`, `zod`, `vega`, `vega-lite`. State — JSON files in `~/.wb-mcp/`.
- **MQTT via system utilities:** `mosquitto_sub -F '%t\t%p'` (TAB separator — correct parsing of control names with spaces like `Input 0`, `Input 0 counter`).
- **Security:** validation of invalid wildcards (`+` inside a MQTT topic level), jobId regex validation, protection from shell injection via `shellQuote`.
- **Charts default to inline Mermaid** (`xychart-beta`, single Y-axis, downsampled to ~30 points) so `wb_history_chart` renders directly in browser-based Claude Code. `format="svg"` / `outputPath=` (or env `WB_CHART_FORMAT=svg`) switches to Vega-Lite SVG with line/bar/area/point/histogram/heatmap/boxplot, dual Y-axis (2 units) and normalization (3+ units). The env override exists for TUI clients that don't render Mermaid blocks (Claude Code CLI, opencode TUI) — set once in `.mcp.json`, every chart goes to `/tmp/wb-charts/<ts>.svg`.

### Key architectural decisions and caught domain bugs

During development and testing on live controllers, around two dozen bugs were caught and fixed — domain ones (mismatch with real WB stack behavior) and integration ones (shell-quoting, async jobs, MQTT parsing). Notable ones:

- **audit**: the `===WB-AUDIT===<name>` parser broke when `cat`-ing a file without trailing `\n` — fixed via `printf "\n===…\n"`.
- **mqtt-controls**: `mosquitto_sub -v` was clipping control names with spaces at the first space — fixed via TAB separator (`-F '%t\t%p'`).
- **async jobs**: `bash -c 'CMD > LOG'` was redirecting only the last command in a `;` chain — fixed via script-file + `StandardOutput=append:`.
- **confed_save**: content as a string broke the config (escape-quoted JSON) — added `JSON.parse` for strings.
- **rules_save/load**: an absolute path was interpreted by RPC as relative → created a file in `/etc/wb-rules/etc/wb-rules/` — fixed via relative path.
- **modbus_scan**: `wb-mqtt-serial/port/Scan` silently skipped live WB devices (observed on WB-MAP6S) — switched to `wb-device-manager/bus-scan/Start`.
- **modbus_template**: scanning 250+ files via jq was timing out — switched to mapping via RPC `config/Load.types`.
- **modbus_add_devices**: `wb-mqtt-serial` schema validation rejected the whole config when a required parameter (typical: WB-MAI6 `in1_type..in6_type`) had no value, halting polling of the entire bus. Now reads the template of every device being added and copies `device.parameters[].default` into the device record; the `added[]` report includes a `paramDefaults` count.

[Unreleased]: https://github.com/wirenboard/wb-ai-skills/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wirenboard/wb-ai-skills/releases/tag/v0.1.0
