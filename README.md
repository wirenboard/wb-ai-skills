# wb-ai-skills

Integration of [Claude Code](https://claude.ai/code) and [opencode](https://opencode.ai) with [Wiren Board](https://wirenboard.com) controllers — control, diagnostics, automation by voice and text.

Three components:

- **`mcp-server/`** — MCP server on Bun with **43 typed tools** (`wb_*`): SSH, MQTT, MQTT-RPC, Modbus, mDNS discovery, background tasks via systemd, history + SVG charts, audit, factoryreset-friendly host keys, network, cloud, systemd units. Details — [`mcp-server/README.md`](mcp-server/README.md).
- **`skills/bash/`** — **21 skills** with Bash recipes (SSH + `mosquitto_*` + `avahi-browse` + `jq`). **Work without the MCP server** — only SSH access and mDNS required.
- **`skills/mcp/`** — **19 thin skills** routing intents to `wb_*` tools of the MCP server. Require a running `mcp-server`.

## What to choose

| Scenario | Install |
|---------|-------|
| Want a simple setup, MCP not ready / no Bun | `skills/bash` |
| Already have Bun/Claude Code, want typed tools | `skills/mcp` + `mcp-server` |
| Both at once | **only one** — `bash` and `mcp` share the same `name:` in frontmatter |

`skills/bash` is the source of domain knowledge (wb-rules syntax, RPC format, Modbus templates, `meta/error` layout per WB Conventions). MCP variants reference bash for deep details and don't duplicate them.

## Quick start

See [INSTALL.md](INSTALL.md) — separate paths for bash-only and mcp-flavor + common issues (mDNS, SSH key, bun, opencode).

Minimal path for the impatient:

```bash
git clone https://github.com/wirenboard/wb-ai-skills.git wb-ai-skills && cd wb-ai-skills

# Bash-flavor for Claude Code (no MCP server, SSH only)
./install-skills.sh bash claude --global

# Or MCP-flavor (requires Bun + .mcp.json config)
cd mcp-server && bun install && cd ..
./install-skills.sh mcp claude --global
```

Usage:

```
> /wiren-board
> find controllers on the network, show their firmware and metrics
> /wb-mqtt-serial
> scan the bus on A25NDEMJ and add what's found to the config
```

## Skills

| Skill | Bash | MCP | Purpose |
|-------|:---:|:---:|------------|
| `wiren-board` | ✓ | ✓ | **Master**: SSH, MQTT, mDNS, security, cross-references |
| `wb-mqtt-serial` | ✓ | ✓ | Modbus/RS-485, wb-mqtt-serial config, enabling channels |
| `serial-templates` | ✓ | ✓ | Custom Modbus templates in `/etc/wb-mqtt-serial.conf.d/templates/` |
| `wb-rules` | ✓ | ✓ | JS rules (ES5), virtual devices, cron, alarms |
| `scenarios` | ✓ | ✓ | Declarative Web UI scenarios (devicesControl/lightControl/thermostat/schedule) |
| `notifications` | ✓ | ✓ | Telegram bot setup, email via msmtp, SMS via mmcli, alarms.conf |
| `troubleshooting` | ✓ | ✓ | General diagnostics (kernel mismatch, failed services, disk, Docker) |
| `troubleshooting-serial` | ✓ | ✓ | RS-485 debug: CRC errors, timeouts, raw packets |
| `services` | ✓ | ✓ | systemd: override-conf, drop-ins, custom units/timers, mask/unmask |
| `network` | ✓ | ✓ | NetworkManager + wb-connection-manager: ethernet/wifi/4G/OpenVPN |
| `wb-cloud` | ✓ | ✓ | Wiren Board Cloud agent: activation, unbinding, custom backend |
| `mqtt-broker` | ✓ | ✓ | mosquitto admin: users, ACL, bridges, TLS |
| `controller-backup` | ✓ | ✓ | tar backup (configs + Docker volumes) + RESTORE.md |
| `controller-update` | ✓ | ✓ | `apt upgrade`, `wb-release -t`, factoryreset (Scenario D) |
| `hardware-modules` | ✓ | ✓ | MOD1-4, WBIO, RS-485, Zigbee, CAN, 1-Wire |
| `software-install` | ✓ | ✓ | Docker-by-default, Z2M-native, Node-RED, HA, Grafana |
| `zigbee` | ✓ | ✓ | Discovery, pairing via zigbee2mqtt; wb-mqtt-zigbee/wb-zigbee2mqtt |
| `history` | ✓ | ✓ | wb-mqtt-db: points + aggregates + Vega-Lite SVG charts |
| `bugreport` | ✓ | ✓ | Collecting data for support + diag archive |
| `diagrams` | ✓ | — | Mermaid automation diagrams |
| `documentation-search` | ✓ | — | Search across Wiren Board wiki/GitHub |

`diagrams` and `documentation-search` don't depend on the controller — MCP variants are redundant. `install-skills.sh` for mcp-flavor pulls them automatically from `skills/bash/`, no need to install separately.

## MCP Tools (brief map)

43 tools in 11 groups. Full table — in [`mcp-server/README.md`](mcp-server/README.md).

- **Discovery (3):** `wb_discover`, `wb_probe`, `wb_add_controller`
- **SSH+files (4):** `wb_ssh_exec`, `wb_ssh_exec_async`, `wb_read_file`, `wb_write_file`
- **Async jobs (3):** `wb_job_status`, `wb_job_tail`, `wb_job_cancel` (via systemd-run + script-file + `StandardOutput=append:`)
- **MQTT (4):** `wb_mqtt_read`, `wb_mqtt_write` (with `retain`/`qos`), `wb_mqtt_list`, `wb_mqtt_rpc`
- **MQTT devices (3):** `wb_mqtt_devices`, `wb_mqtt_controls`, **`wb_mqtt_inventory`** (combined: id+driver+error+controls with unpacked meta and error flags per [WB Conventions](https://github.com/wirenboard/conventions))
- **Confed (2):** `wb_confed_load`, `wb_confed_save` (JSON validation + atomic service restart)
- **wb-rules (5):** `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_disable`, `wb_rules_delete`
- **History (2):** `wb_history`, `wb_history_chart` (Vega-Lite SVG: line/bar/area/heatmap, 1/2/3+ unit strategies)
- **Audit/state (3):** `wb_audit`, `wb_state_save`, `wb_state_diff`
- **Modbus/serial (6):** `wb_modbus_template`, `wb_modbus_templates_list`, `wb_modbus_device_info`, `wb_modbus_probe`, `wb_modbus_ports`, **`wb_modbus_scan`** (via `wb-device-manager/bus-scan/Start`, async, extended Fast Modbus), **`wb_modbus_add_devices`** (auto-add discovered devices to config with `dryRun`)
- **Diagnostics (7):** `wb_metrics`, `wb_logs` (with `since`/`grep`/`grepInvert`), `wb_failed`, `wb_serial_debug`, `wb_systemd_unit`, `wb_network_status`, `wb_cloud_status`

## Architectural notes

- **SSH host-key:** the MCP server uses `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null`. This survives factory reset / FIT firmware reflash without manual `ssh-keygen -R`. A controller in the local network is a trusted environment.
- **Async tasks:** via `systemd-run --collect` + script-file (`/mnt/data/ai/wb-ai-skills/jobs/<id>.sh`) + `StandardOutput=append:`. No shell-redirect tricks, survives SSH disconnect, gc by 24-hour TTL.
- **MQTT error per WB Conventions:** `wb_mqtt_inventory` parses `<...>/meta/error` into flags `{read, write, periodMiss}`. When `read=true`, the value topic contains the **last-known-good** value (see [WB Conventions](https://github.com/wirenboard/conventions)).
- **Names with spaces:** WB-MR6C and similar have controls `Input 0`, `Input 0 counter` — spaces are part of the name. Used `mosquitto_sub -F '%t\t%p'` (TAB separator) to avoid clipping the suffix during parsing.

## Requirements

- **Host machine:** Linux. macOS — not tested, will require installing `avahi-utils` equivalents (on macOS mDNS is handled by the system mDNSResponder, no separate `avahi-browse` utility — needs a port via `dns-sd`). Windows — not supported.
- **Bun 1.3+** — for MCP-flavor.
- **avahi (`avahi-browse`, mDNS)** — for controller discovery.
- **`mosquitto-clients`** — `mosquitto_sub`/`mosquitto_pub` are needed on the host if you use bash-flavor externally; on WB controllers they are present by default.
- **`sshpass`** — if using SSH via password (default `wirenboard`); not needed if using a key.
- **`jq`** — for bash skills with JSON parsing.
- **Claude Code CLI** or **opencode**.

## License

MIT (see [LICENSE](LICENSE)).

## Related projects

- [`wb-ai-helper-desktop`](https://github.com/wirenboard/wb-ai-helper-desktop) — standalone Wiren Board desktop application for talking to controllers via LLM (own DB, UI, encapsulates Anthropic/OpenAI/AITunnel API).
