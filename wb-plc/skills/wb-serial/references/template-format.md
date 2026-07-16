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
        "type": "value",
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
| `type` | MQTT control type. Use `switch`, `value`, `range`, `text`, `pushbutton`. ⚠️ Measurement types (`voltage`, `current`, `power`, `power_consumption`, `temperature`, `pressure`, `lux`, …) are **deprecated** — use `type: "value"` + `units` instead (see WARNING below) |
| `units` | Units string, exactly as in conventions `#### Units` (e.g. `V`, `A`, `W`, `kWh`, `deg C`, `%`, `Pa`, `Hz`). **Not** `°C`, not Cyrillic, no unlisted `kW`/`mWh` |
| `error_value` | If raw == this, control publishes error |
| `unsupported_value` | If raw == this, control isn't published |
| `read_rate_limit_ms` | Don't poll more often than once every N ms |
| `enabled` | `false` — channel disabled by default (enabled via UI) |
| `readonly` | `true` — only read even for `holding`/`coil` |
| `sporadic` | `true` — request only when driver already polls |
| `condition` | Expression on `parameters` fields — channel only visible if true |
| `group` | Group ID for UI |
| `word_order` | `big_endian` (default) or `little_endian` for multi-register values |

### ⚠️ Deprecated control types → `value` + `units`

WB MQTT conventions mark the specialized measurement `type`s as **deprecated**:
> ⚠️ WARNING: These control types are deprecated. It is recommended to use `units` property instead.

Deprecated: `temperature`, `rel_humidity`, `atmospheric_pressure`, `rainfall`, `wind_speed`, `power`, `power_consumption`, `voltage`, `water_flow`, `water_consumption`, `resistance`, `concentration`, `heat_power`, `heat_energy`, `current`, `pressure`, `lux`, `sound_level`.

**Treat any of these in a new template as a blocker** — future wb-mqtt-serial versions may drop support and the control breaks. Instead use `type: "value"` and set the unit explicitly via `units` (from conventions `#### Units`): `voltage`→`{"type":"value","units":"V"}`, `current`→`A`, `power`→`W`, `power_consumption`→`kWh`, `temperature`→`{"type":"value","units":"deg C"}`. `switch`, `value`, `range`, `text`, `pushbutton` are not measurement types — keep them. Source of truth: <https://github.com/wirenboard/conventions> (README, Controls / `#### Units`).

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
  "en": {
    "ACME-EM100_template_title": "ACME EM-100 (1-phase energy meter)"
  },
  "ru": {
    "ACME-EM100_template_title": "ACME EM-100 (1-фазный счётчик электроэнергии)",
    "Voltage": "Напряжение"
  }
}
```

Both `en` and `ru` sections. Key style: the displayed English text is the key by default (channel names, group titles, `enum_titles`, parameter titles); synthetic keys for the template `title` (`<MODEL>_template_title`) and for long or shared strings (`<param_id>_description`). For the full key-style table, capitalization rules and the config-key ↔ translation-key ↔ enum-value ↔ label coherence check — see **`i18n-naming.md`**.
