---
name: wb-mqtt-serial
description: "Modbus/RS-485 driver on a Wiren Board controller via MCP. Config /etc/wb-mqtt-serial.conf, templates, specialized wb_modbus_* / wb_confed_* tools. Enabling/disabling channels, adding devices, scanning the bus, editing wb-mqtt-serial configuration."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-mqtt-serial (MCP)

Modbus/RS-485 driver. Config `/etc/wb-mqtt-serial.conf`, templates `/usr/share/wb-mqtt-serial/templates/` (packaged, don't touch) and `/etc/wb-mqtt-serial.conf.d/templates/` (your own). Work via `wb_modbus_*` and `wb_confed_*` MCP tools — they encapsulate MQTT RPC and confed validation (broken JSON won't be written to `.conf`). `wb_write_file` to `.conf` — only deliberately and with a backup.

Load this on: "channel isn't published", "don't see device on the bus", "polling froze", "enable channel X", "scan the bus", "slave_id / holding / coil / input register", enabling/disabling channels, adding/removing/editing devices in the wb-mqtt-serial config, "add a Modbus device", "remove a device", "clear the device list", "change serial config", "wb-mqtt-serial.conf", editing ports/devices in the config.

**Skill boundary:** signal/CRC/timeout problems — `/troubleshooting-serial`. Authoring a template for a device that isn't in the built-ins — separate skill (you don't do that here).

## Tool routing

| Intent | Tool |
|--------|------|
| List of available templates (type, mqtt-id, name, deprecated) | `wb_modbus_templates_list` |
| Device template contents (all channels, parameters, groups) | `wb_modbus_template` |
| Current device firmware parameters (fw, model, parameters) | `wb_modbus_device_info` |
| Is slave_id N alive on port X | `wb_modbus_probe` |
| RS-485 port parameters | `wb_modbus_ports` |
| What's on the bus (Fast Modbus, WB+Onokom + standard for third-party) | `wb_modbus_scan` (via wb-device-manager, async) |
| Auto-add scanner findings to the config | `wb_modbus_add_devices` (with `dryRun=true` for preview; the tool itself pulls default parameter values from the template — without them the driver's schema validation fails on required parameters) |
| Read `/etc/wb-mqtt-serial.conf` | `wb_confed_load` |
| Save config (validation + service restart) | `wb_confed_save` |
| Current channel value from MQTT | `wb_mqtt_read` |
| List devices / controls | `wb_mqtt_devices`, `wb_mqtt_controls` |
| Write a custom template into `/etc/wb-mqtt-serial.conf.d/templates/` | `wb_write_file` |
| Rare RPC method not covered by specialized tools | `wb_mqtt_rpc` |

## Principles

- **"Channel isn't in MQTT" ≠ "not supported".** Many template channels come with `"enabled": false` (Uptime, Counter, Total, Serial). First `wb_modbus_template`, then conclusions.
- **Look up the template on the controller, not on GitHub.** On the device — current for the firmware. `WebFetch` of templates is almost always wasted.
- **Custom template — last resort.** First check the built-in.
- **Bus scan is slow.** `wb_modbus_scan` takes 5-30 sec — the tool has the right internal timeout.
- **`wb_confed_save` is atomic.** Broken JSON isn't written, polling stays alive.

## Scenario "enable channel X on device Y"

1. `wb_mqtt_devices` (or `wb_mqtt_list prefix=/devices/+/meta/name`) — find `device_id` (e.g. `wb-mr6c_2`).
2. `wb_confed_load path=/etc/wb-mqtt-serial.conf` — find the device in `ports[*].devices[*]`, note `device_type` (e.g. `WB-MR6C`).
3. `wb_modbus_template device_type=<type>` — all template channels and their `enabled`. (Tool accepts `device_type` or `mqtt-id`, case-insensitive.)
4. Edit JSON from step 2 — add/update channel entry, set `"enabled": true`.
5. Show the diff to the user, warn about wb-mqtt-serial restart (polling pauses ~5-10 sec).
6. `wb_confed_save` with full new JSON.
7. After 10-20 sec: `wb_mqtt_read` `/devices/<device_id>/controls/<channel>` (timeout 20 sec, to wait for publication).

## Scenario "what's on the bus"

1. Ports: `wb_modbus_ports` or from `wb_confed_load`.
2. `wb_modbus_scan` on each port with the right baud/parity/stop. Shows what the driver sees. **Finds only WB and Onokom (Fast Modbus).** Third-party — won't see.
3. Compare with `wb_confed_load` — what's already described, what to add.

> `wb_modbus_scan` (this skill) — driver management tool. `wb-device-manager` (the `troubleshooting-serial` skill) — diagnostic tool. Different services, different goals — don't confuse.

## Tool parameters

- **`wb_modbus_template`** — `{device_type}` (or `mqtt-id`, case-insensitive). Returns the contents of the template from `/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json`. List of available types — `wb_modbus_templates_list filter="<substring>"`.
- **`wb_modbus_device_info`** — firmware parameters of a specific device (`fw`, `model`, `parameters`). Does NOT return channels — for channels use `wb_modbus_template`. Accepts either `{device_id: "wb-mr6c_138"}` or a physical address `{path: "/dev/ttyRS485-1", baud_rate: 9600, parity: "N", data_bits: 8, stop_bits: 2, slave_id: 138, device_type: "WB-MR6C"}`.
- **`wb_modbus_probe`** — `{path, slave_id, baud_rate?}` — ping a device on the bus. Defaults: 9600/8/N/2.
- **`wb_modbus_scan`** — `{port?, baud_rate?, data_bits?, parity?, stop_bits?, mode?}` — without `port` scans all ports. Defaults: 9600/8/N/2, mode=all.

## Value control (device/Load, device/Set via wb_mqtt_rpc)

Live channel values, bypassing MQTT publication — `wb_mqtt_rpc service=wb-mqtt-serial method=device/Load params={device_id: "..."}`.

Register write (`device/Set`) — **only on explicit user request**: `wb_mqtt_rpc service=wb-mqtt-serial method=device/Set params={device_id, values: {channel_name: value}}`. This operation is destructive to bus polling at the moment of write.

## Direct file edit — backup mandatory

If for some reason you do without `wb_confed_save` (via `wb_write_file`) — backup first, then restart:

```
wb_ssh_exec sn=<SN> cmd='cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)'
wb_write_file sn=<SN> path=/etc/wb-mqtt-serial.conf content=<JSON>
wb_ssh_exec sn=<SN> cmd='systemctl restart wb-mqtt-serial'
```

This path is justified only when `wb_confed_save` doesn't fit (e.g. you need to write partially invalid JSON for an experiment) — normally always `wb_confed_save`.

## Gotchas

- "Channel isn't supported" based on `wb_mqtt_devices`/`wb_mqtt_controls` without `wb_modbus_template` — see above, `enabled:false` doesn't publish.
- `WebFetch` template from GitHub instead of `wb_modbus_template` — on the device it's more current.
- Custom template before checking the built-in.
- Direct `wb_write_file` to `.conf` without validation — broken JSON will halt bus polling. Use `wb_confed_save`.
- Editing packaged templates in `/usr/share/...` — overwritten by updates. Custom — only in `/etc/wb-mqtt-serial.conf.d/templates/`.

## Documentation

- Wiki: <https://wirenboard.com/wiki/wb-mqtt-serial>
- Source + templates: <https://github.com/wirenboard/wb-mqtt-serial>
- Module pages: `https://wirenboard.com/wiki/<Model>` (WB-MR6C, WB-MSW_v.4 etc.)
