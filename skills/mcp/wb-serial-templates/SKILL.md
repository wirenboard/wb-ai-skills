---
name: wb-serial-templates
description: Authoring custom Modbus templates for wb-mqtt-serial via MCP. /etc/wb-mqtt-serial.conf.d/templates/. File structure, registers, formats, parameters, groups.
allowed-tools: Bash Read Write WebFetch
---

# serial-templates (MCP)

Authoring your own Modbus device templates via `wb_*` tools. When the device isn't among the 250+ built-in ones.

Load this when: "no template for device", "add a Modbus device <third-party>", "create a template", "how to add custom registers".

## Tool routing

| Intent | Tool |
|--------|------|
| Find a similar built-in template as a starting point | `wb_modbus_templates_list filter="<type>"` |
| Read an existing template | `wb_modbus_template device_type=<type> view=full` |
| Write a custom template | `wb_write_file path=/etc/wb-mqtt-serial.conf.d/templates/<name>.json` |
| Apply (driver restart) | `wb_systemd_unit unit=wb-mqtt-serial action=restart` |
| Check template parsing | `wb_logs unit=wb-mqtt-serial since="1m ago" grep="(?i)template"` |
| Check channel publication | `wb_mqtt_read topic=/devices/<device.id>_<slave_id>/controls/<channel>` |
| Direct register read for scale/format calibration | `wb_ssh_exec` `modbus_client_rpc -m rtu -a <slave> -t 4 -r <addr> -c <count> -b <baud> -s 2 -p N <port>` |
| Backup of custom templates | `/wb-controller-backup` (`/etc/wb-mqtt-serial.conf.d/` is already in core-tar) |

## Where templates live

| Directory | What | Editable? |
|-----------|------|-----------|
| `/usr/share/wb-mqtt-serial/templates/` | Packaged WB and Onokom | NO — overwritten by apt |
| `/etc/wb-mqtt-serial.conf.d/templates/<any>.json` | Custom | Yes, survive upgrades |

A custom one with the same `device_type` as a packaged one **overrides** it.

## Minimal template

```json
{
  "title": "ACME EM-100",
  "device_type": "ACME-EM100",
  "group": "g_energy_meters",
  "device": {
    "name": "ACME EM-100",
    "id": "acme-em100",
    "channels": [
      {"name":"Voltage","reg_type":"input","address":0,"format":"u32","scale":0.1,"type":"voltage","units":"V"},
      {"name":"Current","reg_type":"input","address":2,"format":"u32","scale":0.001,"type":"current","units":"A"}
    ]
  }
}
```

## Workflow

1. **Device documentation** — `WebFetch` the manufacturer manual. Without a register table (address/type/scale) don't make a template.
2. **Similar starter template** — `wb_modbus_templates_list filter="<category>"`, then `wb_modbus_template device_type=<similar> view=full`. Copy the structure.
3. **Write the custom one** — `wb_write_file path=/etc/wb-mqtt-serial.conf.d/templates/<name>.json` with one channel for testing.
4. **Driver restart** — `wb_systemd_unit unit=wb-mqtt-serial action=restart`.
5. **Template in the list?** — `wb_modbus_templates_list filter="<your device_type>"` should show it.
6. **Add the device to the config** — `wb_confed_load /etc/wb-mqtt-serial.conf` → append `ports[*].devices` with an entry using your `device_type` → `wb_confed_save`.
7. **Check publication** — `wb_mqtt_read topic=/devices/<device.id>_<slave_id>/controls/<channel>`. Plausible value?
8. **Calibrate `format`/`scale`/`word_order`** — `wb_ssh_exec` `modbus_client_rpc` for direct raw, compare with what the driver publishes.
9. **Expand to all channels** — in batches of 5-10, check after each.
10. **Parameters and groups** — after telemetry.

## Channel fields (key ones)

| Field | Purpose |
|-------|---------|
| `reg_type` | `coil` (FC1), `discrete` (FC2), `holding` (FC3), `input` (FC4) |
| `address` | Register address (0-based; some manuals are 1-based — check) |
| `format` | `u8/s8/u16/s16/u32/s32/float/string/varstring/bcd16/bcd32` |
| `scale` | `value = raw * scale` |
| `word_order` | `big_endian` (default) or `little_endian` for u32/s32/float |
| `error_value` | Raw == this → MQTT `error` |
| `condition` | Visible only if a `parameters` expression is true |
| `enabled` | `false` — present in template, off by default |
| `readonly` | `true` — read-only even for `holding`/`coil` |

## `parameters` and `groups` structure — see bash-flavor twin.

## Gotchas

- **Template in `/usr/share/wb-mqtt-serial/templates/`** — overwritten by apt. Only `/etc/wb-mqtt-serial.conf.d/templates/`.
- **Endianness** — for u32/s32/float use `word_order: little_endian` if the value jumps in 65535-multiples.
- **Scale in reverse** — `raw / 10` vs `raw * 0.1`. Test on a single channel.
- **Duplicate `device_type`** — silently overrides the packaged one. Use a prefix (`ACME-`, `MY-`).
- **Cyrillic in `device.id`** — not allowed, it goes into the topic name. Only `[a-z0-9-]`.
- **0-based vs 1-based address** — Modbus standard is 0-based, manuals are often 1-based.
- **No `error_value`** — FFFF gets published as a valid 65535.

## Related skills

- `/wb-mqtt-serial` — driver config (adding a device with your device_type).
- `/wb-troubleshooting-serial` — CRC/timeout issues during development.
- `/wb-controller-backup` — `/etc/wb-mqtt-serial.conf.d/` is in the archive.

Details (full field list, endianness, format examples) — bash-flavor twin `/wb-serial-templates`.

## Documentation

- Template format: <https://github.com/wirenboard/wb-mqtt-serial/blob/master/docs/template.md>
- Modbus FC: <https://modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf>
- Examples: 250+ templates on the controller, see `wb_modbus_templates_list`.
