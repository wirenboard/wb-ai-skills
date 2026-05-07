# WB MCP Server

MCP server for managing [Wiren Board](https://wirenboard.com) controllers via [Claude Code](https://claude.ai/code).

43 tools: SSH, MQTT (including `wb_mqtt_inventory`), mDNS discovery, wb-rules (including `wb_rules_disable`), Modbus (including `wb_modbus_templates_list` and `wb_modbus_add_devices` for auto-adding what the scanner found), history + SVG charts (`wb_history_chart`), audit, background tasks (via systemd-run + script-file), systemd (`wb_systemd_unit`), network (`wb_network_status`), cloud (`wb_cloud_status`).

## Installation

```bash
cd mcp-server
bun install
```

## Connecting to Claude Code

Copy `.mcp.json.example` → `.mcp.json` into the project or `~/.claude/`:

```json
{
  "mcpServers": {
    "wiren-board": {
      "command": "bun",
      "args": ["run", "/path/to/mcp-server/src/index.ts"],
      "env": {
        "WB_SSH_USER": "root",
        "WB_SSH_PASSWORD": "wirenboard"
      }
    }
  }
}
```

Or via CLI:
```bash
claude mcp add wiren-board -- bun run /path/to/mcp-server/src/index.ts
```

## Tools

### Discovery (3)
| Tool | Description |
|------|----------|
| `wb_discover` | Controllers on the network (mDNS + manual) |
| `wb_probe` | Reachability + system info |
| `wb_add_controller` | Add manually by hostname/IP |

### SSH & Files (4)
| Tool | Description |
|------|----------|
| `wb_ssh_exec` | Command (synchronous, up to 2 min) |
| `wb_ssh_exec_async` | Background task via systemd-run |
| `wb_read_file` | Read a file (up to 64 KB) |
| `wb_write_file` | Write a file (SFTP) |

### Background Jobs (3)
| Tool | Description |
|------|----------|
| `wb_job_status` | Status (running/exited) |
| `wb_job_tail` | Log (incremental) |
| `wb_job_cancel` | Cancel |

### MQTT (4)
| Tool | Description |
|------|----------|
| `wb_mqtt_read` | Retained topic (any, not only WB) |
| `wb_mqtt_write` | Write to topic (with optional `retain`/`qos` — for arbitrary non-WB topics and integrations) |
| `wb_mqtt_list` | Topics by prefix (any `+`/`#` wildcard) |
| `wb_mqtt_rpc` | RPC call (wb-mqtt-serial, confed, wbrules, db_logger) |

### MQTT Devices (3)
| Tool | Description |
|------|----------|
| `wb_mqtt_devices` | Only id → name |
| `wb_mqtt_controls` | Raw topics of a single device |
| `wb_mqtt_inventory` | **Combined**: devices + driver + error + controls (value/type/units/readonly/order/error). One call instead of N+1. Filter by `device` (substring). |

### Confed Configuration (2)
| Tool | Description |
|------|----------|
| `wb_confed_load` | Load config (/etc/wb-mqtt-serial.conf, /etc/wb-hardware.conf) |
| `wb_confed_save` | Save (validation + service restart) |

### wb-rules (5)
| Tool | Description |
|------|----------|
| `wb_rules_list` | List rules (.js, enabled/disabled) |
| `wb_rules_load` | Read rule |
| `wb_rules_save` | Save (JS validation + reload) |
| `wb_rules_delete` | Delete entirely (`Editor/Remove`) |
| `wb_rules_disable` | Disable a file (`<name>.js` → `<name>.js.disabled`) without deleting |

### History (2)
| Tool | Description |
|------|----------|
| `wb_history` | Data from wb-mqtt-db (points + min/max/avg) |
| `wb_history_chart` | SVG chart via Vega-Lite. Types: line/bar/area/point/histogram/heatmap/boxplot. 1 unit → single scale, 2 → dual Y-axis, 3+ → normalization to [0;1] |

### Audit & State (3)
| Tool | Description |
|------|----------|
| `wb_audit` | Audit: packages, services, custom files |
| `wb_state_save` | Snapshot of system state |
| `wb_state_diff` | Comparison with snapshot |

### Modbus / wb-mqtt-serial (6)
| Tool | Description |
|------|----------|
| `wb_modbus_templates_list` | List of available templates: type, mqtt-id, name, deprecated, group. RPC `wb-mqtt-serial/config/Load.types` |
| `wb_modbus_template` | Template content (all channels, parameters, groups, translations). By device_type looks up mqtt-id via RPC and reads `/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json` |
| `wb_modbus_device_info` | Current firmware parameters (fw, model, parameters) — NOT a channel list (for channels: `wb_modbus_template`) |
| `wb_modbus_probe` | Ping device on the bus |
| `wb_modbus_ports` | RS-485 port parameters |
| `wb_modbus_scan` | Full bus scan (mode=all). RPC requires all serial parameters — defaults 9600/8/N/2 |

### Diagnostics (7)
| Tool | Description |
|------|----------|
| `wb_metrics` | Load, memory, disk |
| `wb_logs` | Service logs (journalctl) with `since`/`until`/`grep`/`grepInvert` |
| `wb_failed` | Failed systemd services |
| `wb_serial_debug` | Collect raw RS-485 packets |
| `wb_systemd_unit` | Status (parsed), start/stop/restart/enable/disable/mask/cat/list-deps |
| `wb_network_status` | Interfaces + NM connections + default route + optional ping |
| `wb_cloud_status` | wb-cloud-agent: service, MQTT status, certificate, providers |

## Environment variables

| Variable | Default | Description |
|------------|-------------|----------|
| `WB_SSH_USER` | `root` | SSH login |
| `WB_SSH_PASSWORD` | `wirenboard` | SSH password |
| `WB_SSH_KEY` | — | Path to private key |
| `WB_DISCOVERY_INTERVAL` | `15000` | mDNS scan interval (ms) |

## Requirements

- [Bun](https://bun.sh) 1.3+
- Local network with Wiren Board controllers
- SSH access to controllers
