# wb-mqtt-serial template format

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
| `name` | Control name in MQTT (spaces OK) |
| `reg_type` | `coil` (FC1, RW), `discrete` (FC2, RO), `holding` (FC3, RW), `input` (FC4, RO) |
| `address` | Register address (decimal) |
| `format` | `u8`, `s8`, `u16`, `s16`, `u32`, `s32`, `u64`, `s64`, `bcd16`, `bcd32`, `bcd64`, `float`, `double`, `string`, `varstring` |
| `scale` | Multiplier `value = raw * scale` |
| `offset` | Added after scale |
| `round_to` | Round to N digits |
| `type` | MQTT control type: `switch`, `value`, `voltage`, `current`, `power`, `energy_power`, `temperature`, `pressure`, `range`, `text`, `pushbutton` |
| `units` | Units (V, A, °C, mWh) |
| `error_value` | If raw == this, control publishes error |
| `unsupported_value` | If raw == this, control isn't published |
| `read_rate_limit_ms` | Don't poll more often than once every N ms |
| `enabled` | `false` — channel disabled by default (enabled via UI) |
| `readonly` | `true` — only read even for `holding`/`coil` |
| `sporadic` | `true` — request only when driver already polls |
| `condition` | Expression on `parameters` fields — channel only visible if true |
| `group` | Group ID for UI |
| `word_order` | `big_endian` (default) or `little_endian` for multi-register values |

### Endianness

Modbus is byte big-endian, but for u32/s32/float the **word** order (16-bit registers) is often little-endian for some manufacturers. Symptom: value "jumps strangely" — try `"word_order": "little_endian"`.

### `string` / `varstring`

```json
{
  "name": "FW Version",
  "reg_type": "input",
  "address": 250,
  "format": "string",
  "size": 8,
  "type": "text"
}
```

## `parameters` — firmware settings

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

`condition` in a channel can look at a parameter `id`: `"condition": "in0_mode==3"`.

## `groups` — UI grouping

```json
"groups": [
  {"id": "g_inputs", "title": "Inputs"},
  {"id": "g_in0_channels", "title": "Input 0", "group": "g_inputs"}
]
```

## `translations` — i18n

```json
"translations": {
  "ru": {
    "Voltage": "Напряжение"
  }
}
```
