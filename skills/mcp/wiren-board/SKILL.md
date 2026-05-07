---
name: wiren-board
description: Master skill for Wiren Board controllers via wb_* MCP tools. Load on any mention of WB, MQTT topics, Modbus devices on the bus, wb-rules automation, or hardware config. Routes intents to the right wb_* tool, plus mDNS discovery, serial-number conventions, and safety rules.
allowed-tools: Bash Read Write Grep Glob WebFetch WebSearch
---

# wiren-board (MCP)

**Skill set version:** 0.1.0 · flavor: mcp · single source of truth: `VERSION` at the repo root. The MCP server reports the same version via the standard MCP `initialize` handshake — visible in Claude Code under `/mcp` as `wiren-board v<VERSION>`. Skill set and server are guaranteed to match because both read the same file.

Master skill for working with Wiren Board controllers via `wb_*` MCP tools. All controller operations go through MCP, not directly via `ssh`/`mosquitto_*`/`avahi-browse`. Load this on any mention of WB controllers, MQTT topics, devices on the bus, automation rules, hardware configuration.

## Tool routing

| Intent | Tool |
|--------|------|
| Find controllers on the network | `wb_discover` (mDNS + manual) |
| Controller reachability + system info | `wb_probe` |
| Add a controller manually (no mDNS, have IP) | `wb_add_controller` |
| Command on controller (quick, up to 2 min) | `wb_ssh_exec` |
| Long command (`apt`, `docker pull/build`, `wb-release`) | `wb_ssh_exec_async` → `wb_job_status` / `wb_job_tail` / `wb_job_cancel` |
| Read a file (up to 64 KB) | `wb_read_file` |
| Write a file (SFTP) | `wb_write_file` |
| Read retained topic | `wb_mqtt_read` |
| Write to MQTT (control → `<topic>/on`) | `wb_mqtt_write` |
| List topics by prefix | `wb_mqtt_list` |
| MQTT RPC (wb-mqtt-serial, confed, wbrules, db_logger) | `wb_mqtt_rpc` |
| List devices / controls | `wb_mqtt_devices`, `wb_mqtt_controls` |
| Value history | `wb_history` |
| SVG history chart (line/bar/area/heatmap…) | `wb_history_chart` |
| Audit / state snapshot | `wb_audit`, `wb_state_save`, `wb_state_diff` |
| Metrics (load/RAM/disk), unit logs, failed services | `wb_metrics`, `wb_logs`, `wb_failed` |
| Modbus: template / templates list / firmware / probe / ports / scan / auto-add | `wb_modbus_template`, `wb_modbus_templates_list`, `wb_modbus_device_info`, `wb_modbus_probe`, `wb_modbus_ports`, `wb_modbus_scan`, `wb_modbus_add_devices` |
| Modbus serial debug (raw RS-485 packets) | `wb_serial_debug` |
| wb-rules: list / load / save / disable / delete | `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_disable`, `wb_rules_delete` |
| Confed: load / save | `wb_confed_load`, `wb_confed_save` |

## Discovering controllers

`wb_discover` is the only path. Internally it merges mDNS scan (via `bonjour-service` + `avahi-browse`) and manual additions (`wb_add_controller`). Returns `sn`, `host`, addresses, `reachable`, `fw`. Don't poke `avahi-browse`/`ping` by hand.

**Cold cache is normal.** Discovery polls the network every `WB_DISCOVERY_INTERVAL` ms (default 15000). If the controller just appeared or the MCP server just started, the first `wb_discover` may return an empty or incomplete list. Wait ~5-15 sec and retry.

If the controller isn't visible via mDNS at all (Docker environment, closed multicast, different VLANs):

- `wb_add_controller` with `host=<IP-or-hostname>` — creates an entry, attempts to fetch the SN.

The addresses returned by `wb_discover` don't include IPv6 link-local (`fe80::*`) — for SSH from this host they're useless without specifying a scope-id anyway.

### Serial number format

- SN is alphanumeric, like `A25NDEMJ` (length may vary).
- Hostname: `wirenboard-<sn>.local`.
- All tools accept `sn`; mDNS resolution happens internally.
- Get the SN from the controller manually (if discovery failed): `wb_ssh_exec` `cat /var/lib/wirenboard/short_sn.conf` or `wb_mqtt_read` `/devices/system/controls/Short SN`.

### Firmware version

- Via `wb_probe` — comes in the system info.
- Direct files if needed: `wb_read_file` `/etc/wb-fw-version` (format — timestamp `YYYYMMDDHHMM`) and `/usr/lib/wb-release` (shell notation: `RELEASE_NAME`, `SUITE`, `TARGET`).

## Commands on the controller

### Quick (up to 2 minutes)

`wb_ssh_exec` with `sn` and `cmd`. The tool uses a connection pool and returns stdout/stderr/exit_code.

Command examples (what to put in `cmd`):

- `systemctl is-active wb-mqtt-serial`
- `df -h / /mnt/data`
- `uptime; free -h`
- `ls /dev/ttyRS485-* /dev/ttyMOD* 2>/dev/null`

### Long (apt, tar, build, wb-release)

**Only** via `wb_ssh_exec_async`. Synchronous `wb_ssh_exec` will timeout, breaking apt mid-transaction.

Cycle:

1. `wb_ssh_exec_async` `cmd="..."` → returns `job_id`.
2. `wb_job_tail` `job_id=...` → incremental log (call periodically).
3. `wb_job_status` `job_id=...` → `running` / `exited` (`exit_code`).
4. `wb_job_cancel` `job_id=...` — if cancellation is needed (only before the critical install phase).

Internally the tool uses systemd-run, the job survives connection drop.

## MQTT operations

### Reading and writing

| Scenario | Tool |
|----------|------|
| Read control value | `wb_mqtt_read` topic=`/devices/<d>/controls/<c>` |
| Read type/meta | `wb_mqtt_read` topic=`/devices/<d>/controls/<c>/meta/type` |
| Write control value | `wb_mqtt_write` topic=`/devices/<d>/controls/<c>/on` value=`...` |
| List devices | `wb_mqtt_devices` or `wb_mqtt_list` `prefix=/devices/+/meta/name` |
| List device controls | `wb_mqtt_controls` or `wb_mqtt_list` `prefix=/devices/<d>/controls/+` |

**Important:** to control values, publish to `<topic>/on`, not to `<topic>` itself — otherwise the value is overwritten by the driver.

### MQTT RPC

`wb_mqtt_rpc` encapsulates client_id generation, reply-topic subscription, pause before publishing the request, and timeout. Don't write `mosquitto_sub`/`mosquitto_pub` by hand for standard services.

Parameters: `service` (e.g. `wb-mqtt-serial`), `method` (`config/Load`), `params` (object, mandatory — even empty `{}`), `timeout` (sec, default reasonable per method).

For specialized operations there are higher-level tools — prefer them:

| Goal | Tool |
|------|------|
| List of available templates | `wb_modbus_templates_list` (without filter — group summary, with filter — flat list) |
| Device template contents (by device_type or mqtt-id, case-insensitive) | `wb_modbus_template` |
| Device firmware parameters (fw, model, parameters) | `wb_modbus_device_info` |
| Ping a device on the bus | `wb_modbus_probe` |
| RS-485 port parameters | `wb_modbus_ports` |
| Bus scanning | `wb_modbus_scan` (via wb-device-manager, async; `scan_type:"extended"`=Fast Modbus, `"standard"`=regular) |
| Add scan findings to the config | `wb_modbus_add_devices` (one at a time, dryRun=true for preview) |
| Raw RS-485 driver debug logs | `wb_serial_debug` |
| Read `/etc/wb-mqtt-serial.conf` or `/etc/wb-hardware.conf` | `wb_confed_load` |
| Write a config with validation and restart | `wb_confed_save` |
| List / load / save / disable / delete rules | `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_disable`, `wb_rules_delete` |

`wb_mqtt_rpc` is needed for rare/non-standard calls (e.g. `db_logger`, manual services).

### Available RPC services (via `wb_mqtt_rpc` or specialized tools)

#### wb-mqtt-serial — Modbus/RS-485 driver

| Method | Tool | params |
|--------|------|--------|
| `config/Load` (config + `types[]` of templates) | `wb_mqtt_rpc` or `wb_confed_load(path=/etc/wb-mqtt-serial.conf)` | `{}` |
| Device template (channels/parameters/groups) | `wb_modbus_template` | `{device_type:"WB-MR6C"}` or `{device_type:"wb-mr6c"}` (mqtt-id, case-insensitive) |
| `device/LoadConfig` (firmware fw/model/parameters) | `wb_modbus_device_info` | `{device_id:"wb-mr6c_138"}` or full set by address |
| `device/Probe` | `wb_modbus_probe` | `{path,baud_rate,slave_id}` |
| Bus scan (via `wb-device-manager/bus-scan`) | `wb_modbus_scan` | `{port?, baud_rate?, scan_type:"extended"\|"standard"}` |
| Auto-add findings to config | `wb_modbus_add_devices` | `{dryRun:true}` for preview |
| `ports/Load` | `wb_modbus_ports` | `{}` |

#### confed — config editor

| Method | Tool | Purpose |
|--------|------|---------|
| `Editor/Load` | `wb_confed_load` | Load config by path |
| `Editor/Save` | `wb_confed_save` | Save (JSON validation + atomic service restart) |

**Use `wb_confed_save` instead of `wb_write_file`** for `/etc/wb-mqtt-serial.conf`, `/etc/wb-hardware.conf`, `/etc/wb-mqtt-mbgate.conf`, etc. — it validates JSON and atomically restarts the dependent service. Direct write of broken JSON via `wb_write_file` may stop bus polling.

#### wbrules — rules engine

| Method | Tool |
|--------|------|
| `Editor/List` | `wb_rules_list` |
| `Editor/Load` | `wb_rules_load` |
| `Editor/Save` | `wb_rules_save` (JS validation + hot reload) |
| Removal | `wb_rules_delete` (only with explicit OK) |

## File operations

| Action | Tool |
|--------|------|
| Read a file (≤64 KB) | `wb_read_file` |
| Write a file (SFTP, any size within disk) | `wb_write_file` |
| Download a directory recursively | outside MCP — local `scp -r root@<host>:<dir> <local>` |
| Upload a directory recursively | outside MCP — local `scp -r <local> root@<host>:<dir>` |

`scp` for directories goes through local Bash bypassing MCP because the `wb_write_file` tool handles one file per call.

For writing many small configs (e.g. on backup restore) use `wb_write_file` in a loop or `wb_ssh_exec_async` `cmd='tar -xzf /tmp/backup.tar.gz -C /'`.

## Safety rules

### FORBIDDEN

- **Do NOT run FIT firmware** (`wb-fw-update`, `swupdate`, `wb-run-update`, `fit-update`) — firmware only via the controller's web UI. FIT rewrites the rootfs entirely, an error can brick the controller.
- **`wb-factoryreset` — only with explicit user confirmation and a mandatory backup before.** Wipes all user data (configs, rules, templates, Docker images), root password reverts to `wirenboard`, custom SSH keys are gone. Full scenario — in `/wb-controller-update` (Scenario D). Don't run on ambiguous wording ("clean", "reset").

### Backup before editing configs — MANDATORY

Before any write to a configuration file:

```
wb_ssh_exec sn=<SN> cmd='cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)'
```

Files requiring backup: `wb-mqtt-serial.conf`, `wb-hardware.conf`, files in `/etc/network/`, `/etc/mosquitto/`, `/etc/wb-rules/`.

### RPC/specialized tools instead of direct edits

| Config | Tool | Why |
|--------|------|-----|
| `/etc/wb-mqtt-serial.conf` | `wb_confed_save` | JSON validation + atomic driver restart |
| Rules `/etc/wb-rules/*.js` | `wb_rules_save` | JS validation + hot reload |
| `/etc/wb-hardware.conf` | `wb_confed_save` | Validation + apply without reboot |

### User confirmation

**Ask for confirmation before:**
- Destructive operations: `rm`, `reboot`, `dpkg --remove`, `apt-get purge`, `wb_rules_delete`.
- Restarting critical services: `systemctl restart wb-mqtt-serial`, `systemctl restart mosquitto`.
- Network configuration changes (can lose access).
- Stopping Docker containers.

**WITHOUT confirmation (run immediately):**
- Diagnostics and reads: `wb_metrics`, `wb_logs`, `wb_failed`, `wb_mqtt_read`, `wb_mqtt_list`, `wb_audit`, `wb_modbus_*` read-only methods.
- Bus scanning (`wb_modbus_scan`) — read-only for devices.
- Viewing rules/configs (`wb_rules_load`, `wb_confed_load`).

### Logs — only fresh

In `wb_logs` specify a reasonable `since` or `lines`. Don't pull the entire journal — it can be huge for unit logs on controllers.

## Typical diagnostic scenarios

| Scenario | Tools |
|----------|-------|
| Failed services | `wb_failed` |
| Space and load | `wb_metrics` |
| Errors in journal | `wb_logs` `priority=err` (or `wb_ssh_exec` `journalctl -p err -n 50 --no-pager`) |
| Kernel mismatch | `wb_audit` will flag the discrepancy or `wb_ssh_exec` `uname -r; dpkg -l linux-image-wb*` |
| List of serial ports | `wb_ssh_exec` `ls /dev/ttyRS485-* /dev/ttyMOD* 2>/dev/null` |
| Is MQTT broker alive | `wb_mqtt_list` (if it returns topics — broker is alive); if in doubt `wb_logs unit=mosquitto` |

## Skills

Available skills for specific tasks — call `/skill-name` when the task falls into their area:

| Skill | Area |
|-------|------|
| `/wb-mqtt-serial` | Modbus device configuration, channel enable/disable, device addition |
| `/wb-serial-templates` | Authoring custom Modbus templates (when there's no native one) |
| `/wb-rules` | JS automation rules (defineRule, virtual devices, timers, cron) |
| `/wb-scenarios` | Declarative Web UI scenarios (devicesControl, lightControl, thermostat, schedule) |
| `/wb-notifications` | Telegram/Email/SMS from rules (`Notify.*`), `alarms.conf` |
| `/wb-troubleshooting` | General diagnostics: failed services, disk space, kernel mismatch, Docker |
| `/wb-troubleshooting-serial` | RS-485/Modbus: CRC errors, timeouts, signal issues |
| `/wb-services` | systemd: override-conf, drop-ins, custom units/timers, mask/unmask |
| `/wb-network` | NetworkManager + wb-connection-manager: ethernet/wifi/4G/OpenVPN, failover |
| `/wb-cloud` | Wiren Board Cloud agent: activation, status, unbinding |
| `/wb-mqtt-broker` | mosquitto admin: users, ACL, bridges, TLS |
| `/wb-controller-backup` | Full backup: configs, packages, data, Docker volumes |
| `/wb-controller-update` | Firmware and package updates |
| `/wb-hardware-modules` | Expansion modules (MOD1-MOD4): Zigbee, CAN, RS-485, relay |
| `/wb-software-install` | Software installation: Docker, Zigbee2MQTT, Home Assistant, Node-RED, Grafana |
| `/wb-zigbee` | Zigbee devices: pairing, control, groups, OTA |
| `/wb-history` | Data history, charts (`wb_history_chart`), export |
| `/wb-bugreport` | Composing a bug report with diagnostic archive |

`/wb-diagrams` (Mermaid) and `/wb-documentation-search` exist only in bash flavor — they don't depend on the controller, the MCP twin makes no sense. If installed in parallel from `skills/bash/` — they'll be available.

## Operating principles

1. **Diagnostics first, then actions.** Before changing anything — figure out the current state. `wb_confed_load`, `wb_logs`, `wb_mqtt_read`/`wb_mqtt_list`, `wb_metrics`.

2. **Don't guess topic names.** Device and control names depend on the specific controller's configuration. First `wb_mqtt_devices` / `wb_mqtt_controls`.

3. **Don't ask "would you like" — do it.** The user will stop you if anything. Exception — destructive operations (see safety rules).

4. **Act autonomously.** Verify facts via tools, don't ask "is X installed?" — find out yourself:
   - `wb_ssh_exec` `dpkg -l | grep docker`
   - `wb_ssh_exec` `ip addr show`
   - `wb_audit` for the overall picture

5. **Templates and configs from the controller, not the internet.** On the device, the version is current for the installed firmware. Don't WebFetch templates from GitHub — use `wb_modbus_template`.

6. **Documentation before fixing.** For typical tasks (Docker, Zigbee, Home Assistant) first read the corresponding wiki page via WebFetch: `https://wirenboard.com/wiki/<Topic>`.
