---
name: serial-templates
description: Creating custom Modbus templates for wb-mqtt-serial. When the device isn't among the built-in templates. /etc/wb-mqtt-serial.conf.d/templates/. File structure, registers, formats, parameters, groups.
allowed-tools: Bash Read Write WebFetch
---

# serial-templates

Creating your own Modbus device templates for `wb-mqtt-serial`. Used when the manufacturer isn't WB/Onokom (no built-in template) or when you need to add custom registers to an existing one.

Load this on: "no template for the device", "add a third-party Modbus device", "create a template", "how to add custom registers", "template for an energy meter", "Modbus thermometer".

## Where templates live

| Directory | What | Editable? |
|---------|-----|----------------|
| `/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json` | Packaged WB and Onokom templates | NO — overwritten by `apt upgrade` |
| `/etc/wb-mqtt-serial.conf.d/templates/<any-name>.json` | Custom templates | Yes, survive upgrade |
| `/etc/wb-mqtt-serial.conf.d/confs/*.conf` | Custom parts of the main config | Less commonly used |

`wb-mqtt-serial` scans both directories at start. A custom template with the same `device_type` as a packaged one **overrides** the packaged one (useful for patches; risky because you'll forget).

## Minimal template structure

```json
{
  "title": "ACME EM-100 (1-phase energy meter)",
  "device_type": "ACME-EM100",
  "group": "g_energy_meters",
  "device": {
    "name": "ACME EM-100",
    "id": "acme-em100",
    "channels": [
      {
        "name": "Voltage",
        "reg_type": "input",
        "address": 0,
        "format": "u16",
        "scale": 0.1,
        "type": "voltage",
        "units": "V"
      },
      {
        "name": "Current",
        "reg_type": "input",
        "address": 2,
        "format": "u32",
        "scale": 0.001,
        "type": "current",
        "units": "A"
      }
    ]
  }
}
```

`device_type` — what goes into `/etc/wb-mqtt-serial.conf` (`ports[*].devices[*].device_type`).
`device.id` — MQTT topic prefix (`wb-mqtt-serial` will create `/devices/<id>_<slave_id>/...`).

## Channel fields (full set)

| Field | Purpose |
|------|-----------|
| `name` | Control name in MQTT (spaces OK: `Input 0`, `Input 0 counter`) |
| `reg_type` | `coil` (FC1, RW), `discrete` (FC2, RO), `holding` (FC3, RW), `input` (FC4, RO) |
| `address` | Register address (decimal) |
| `format` | `u8`, `s8`, `u16`, `s16`, `u32`, `s32`, `u64`, `s64`, `bcd16`, `bcd32`, `bcd64`, `float`, `double`, `string`, `varstring` |
| `scale` | Multiplier `value = raw * scale` |
| `offset` | Added after scale |
| `round_to` | Round to N digits |
| `type` | MQTT control type: `switch`, `value`, `voltage`, `current`, `power`, `energy_power`, `temperature`, `pressure`, `range`, `text`, `pushbutton` |
| `units` | Units (V, A, °C, mWh) |
| `error_value` | If raw == this, control publishes error |
| `unsupported_value` | If raw == this, control isn't published (used by manufacturer for "no data") |
| `read_rate_limit_ms` | Don't poll more often than once every N ms (for slow registers) |
| `enabled` | `false` — channel exists in template but disabled by default (enabled via UI) |
| `readonly` | `true` — even for `holding`/`coil`, only read |
| `sporadic` | `true` — request only when the driver already polls (not on first start) |
| `condition` | Expression on `parameters` fields — channel only visible if true (see below) |
| `group` | Group ID for UI (see `groups` below) |
| `word_order` | `big_endian` (default) or `little_endian` for multi-register values |

### Endianness

Modbus is byte big-endian, but for u32/s32/float the **word** order (16-bit registers) is often little-endian for some manufacturers. Symptom: value "jumps strangely" — try `"word_order": "little_endian"` (or the opposite of big/little).

### `string` / `varstring`

```json
{
  "name": "FW Version",
  "reg_type": "input",
  "address": 250,
  "format": "string",
  "size": 8,           // length in registers (= 16 bytes)
  "type": "text"
}
```

`varstring` — variable-length string with null terminator.

## `parameters` — firmware settings

Registers shown by the UI as "device settings" (not telemetry):

```json
"parameters": [
  {
    "id": "in0_mode",
    "title": "Input 0 mode",
    "address": 1100,
    "reg_type": "holding",
    "format": "u16",
    "default": 0,
    "enum": [0, 1, 2, 3],
    "enum_titles": [
      {"en": "Switch"},
      {"en": "Push button"},
      {"en": "RS-trigger"},
      {"en": "Counter"}
    ],
    "group": "g_in0_setup"
  }
]
```

`condition` in a channel can look at a parameter `id`: `"condition": "in0_mode==3"` — channel visible only if parameter == 3.

## `groups` — UI grouping

```json
"groups": [
  {"id": "g_inputs", "title": "Inputs"},
  {"id": "g_in0_channels", "title": "Input 0", "group": "g_inputs"},
  {"id": "g_in0_setup", "title": "Input 0 setup", "group": "g_inputs"}
]
```

Hierarchy: `group` references the parent's `id`. Web UI renders expanded sections.

## `translations` — i18n

```json
"translations": {
  "ru": {
    "Voltage": "Напряжение",
    "Input 0": "Вход 0",
    "g_inputs": "Входы"
  }
}
```

Web UI shows translations for the chosen language.

## Template creation workflow

### 1. Device documentation

`WebFetch` the manufacturer's manual — register table (addresses, types, scale). Without it, don't make a template; guessing = endless debugging.

### 2. Copy a similar built-in template as a starter

```bash
ssh root@<HOST> 'cp /usr/share/wb-mqtt-serial/templates/config-wb-mr6c.json /etc/wb-mqtt-serial.conf.d/templates/acme-em100.json'
ssh root@<HOST> 'vi /etc/wb-mqtt-serial.conf.d/templates/acme-em100.json'   # edit for your device
```

Minimum: change `device_type`, `device.id`, `device.name`, `title`, then rewrite `channels` for your register table.

### 3. Test on one channel

First a template with **one** channel. Add the device to `/etc/wb-mqtt-serial.conf` via confed, verify the channel publishes and the value is plausible:

```bash
ssh root@<HOST> "mosquitto_sub -t '/devices/<device.id>_<slave_id>/controls/<channel>' -C 1 -W 5"
```

If the value doesn't match expectations — tweak `format`, `scale`, `word_order`. Direct ground-truth measurement via `modbus_client_rpc`:

```bash
ssh root@<HOST> 'modbus_client_rpc -m rtu -a <slave> -t 4 -r <addr> -c <count> -b <baud> -s 2 -p N <port>'
```

(`-t 4` = `input registers`, FC4. See `/troubleshooting-serial`.)

### 4. Expand to all channels

Add in batches of 5-10, after each — verify via MQTT.

### 5. Parameters and groups

When base telemetry works — add `parameters` for settings, `groups` for UI.

### 6. Template in Git/backup

A custom template won't survive FIT — must go into `/controller-backup` (it picks up `/etc/wb-mqtt-serial.conf.d/` itself).

## Loading / testing without restart

```bash
ssh root@<HOST> 'systemctl restart wb-mqtt-serial'
```

Template parsing logs:

```bash
ssh root@<HOST> 'journalctl -u wb-mqtt-serial -n 50 --no-pager | grep -iE "(template|<device.id>)"'
```

Errors like `Failed to parse template` / `Unknown register type` — syntax.

## Example: 1-phase energy meter

Take a hypothetical ACME EM-100 with the following table:

| Address | Register | Format | Scale | What |
|-------|---------|--------|-------|-----|
| 0-1 | input | u32 | 0.1 | Voltage (mV→V) |
| 2-3 | input | u32 | 0.001 | Current (mA→A) |
| 4-5 | input | s32 | 0.01 | Active power (W) |
| 6-7 | input | u32 | 0.001 | Active energy (Wh→kWh) |

```json
{
  "title": "ACME EM-100",
  "device_type": "ACME-EM100",
  "group": "g_energy_meters",
  "device": {
    "name": "ACME EM-100",
    "id": "acme-em100",
    "channels": [
      {"name": "Voltage", "reg_type": "input", "address": 0, "format": "u32", "scale": 0.1, "type": "voltage", "units": "V"},
      {"name": "Current", "reg_type": "input", "address": 2, "format": "u32", "scale": 0.001, "type": "current", "units": "A"},
      {"name": "Active Power", "reg_type": "input", "address": 4, "format": "s32", "scale": 0.01, "type": "power", "units": "W"},
      {"name": "Active Energy", "reg_type": "input", "address": 6, "format": "u32", "scale": 0.001, "type": "energy_power", "units": "kWh"}
    ]
  }
}
```

## Pitfalls

- **Template in `/usr/share/wb-mqtt-serial/templates/`** — overwritten on upgrade. Only `/etc/wb-mqtt-serial.conf.d/templates/`.
- **Endianness** — most common error for u32/s32/float. If the value jumps by a 65535 factor — `word_order: little_endian`.
- **Scale in the wrong direction** — manufacturers sometimes give "raw / 10" instead of "raw × 0.1". Test on one channel solves it.
- **Duplicate `device_type`** — if same as a packaged one, silently overrides. A prefix like `ACME-` helps.
- **Cyrillic in `device.id`** — forbidden (it goes into the topic name). Only `[a-z0-9-]`.
- **Address 0-based vs 1-based** — Modbus standard is 0-based, many manuals give 1-based (FFFF=65535 → 1-based 1, 0-based 0). Check the device spec for which numbering.
- **No `error_value`** — if the device returns FFFF for "no data", MQTT will show 65535 as a valid value.

## Documentation

- Documentation — template format: <https://github.com/wirenboard/wb-mqtt-serial/blob/master/docs/template.md>
- Modbus FC: <https://modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf>
- Examples — `/usr/share/wb-mqtt-serial/templates/` on the controller (250+ templates).
