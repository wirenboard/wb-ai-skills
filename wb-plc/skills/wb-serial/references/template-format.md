# wb-mqtt-serial template format — where the rules live

The template JSON has one canonical definition, and it is **public upstream**. This skill
points at those sources instead of keeping its own copy — the enums and lists there grow
over time, and a second copy drifts. Every link below is public; an agent can read it live.

## What to check → the public source of truth

| Concern | Source |
|---|---|
| Structure, `reg_type`/`format`/control `type`/`word_order` enums, address patterns | driver **JSON Schema**: [`wb-mqtt-serial-device-template.schema.json`](https://github.com/wirenboard/wb-mqtt-serial/blob/master/wb-mqtt-serial-device-template.schema.json) + [`wb-mqtt-serial-confed-common.schema.json`](https://github.com/wirenboard/wb-mqtt-serial/blob/master/wb-mqtt-serial-confed-common.schema.json) (shared `$ref` definitions) |
| `units` string — exact form (`deg C`, not `°C`; no unlisted `kW`/`mWh`) | [wirenboard/conventions](https://github.com/wirenboard/conventions) → `#### Units` |
| Deprecated measurement control types → `type:"value"` + `units` | [wirenboard/conventions](https://github.com/wirenboard/conventions) → Controls |
| MQTT topic names (`name`), control types, text style | conventions + [wirenboard/wb-standards](https://github.com/wirenboard/wb-standards) (WB-STD-001/002) |

Read the value list from the **current** schema/conventions, not from memory — a hardcoded
copy is the main source of false "invalid value" findings.

**Deprecated control types** are the one rule worth stating outright: the specialized
measurement `type`s (`voltage`, `current`, `power`, `temperature`, …) are deprecated in the
conventions — use `type: "value"` + `units` instead. The authoritative, current list lives
in conventions → Controls; don't trust a copy.

## Minimal skeleton (orientation only)

```json
{
  "title": "ACME EM-100 (1-phase energy meter)",
  "device_type": "ACME-EM100",
  "group": "g_energy_meters",
  "device": {
    "name": "ACME EM-100",
    "id": "acme-em100",
    "channels": [
      { "name": "voltage", "reg_type": "input", "address": 0,
        "format": "u16", "scale": 0.1, "type": "value", "units": "V" }
    ]
  }
}
```

The two controller-side load-bearing keys:

- `device_type` — written into `/etc/wb-mqtt-serial.conf` (`ports[*].devices[*].device_type`);
  a custom template reusing a packaged `device_type` silently overrides it (use a prefix like `ACME-`).
- `device.id` — MQTT topic prefix: the driver publishes to `/devices/<id>_<slave_id>/...`.
  Only `[a-z0-9-]` (it goes into the topic name; no Cyrillic).

Everything else (channel fields, endianness, `parameters`/`groups`/`translations`) is
defined in the schema and conventions above.
