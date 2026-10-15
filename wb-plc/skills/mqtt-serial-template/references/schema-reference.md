# schema-reference — layer 1: the driver JSON Schema (format)

The source of truth for **format**: a mismatch is a **blocker** (wb-mqtt-serial won't load the template). This file does not restate the schema — it tells you where to look and how to check.

- [`wb-mqtt-serial-device-template.schema.json`](https://github.com/wirenboard/wb-mqtt-serial/blob/master/wb-mqtt-serial-device-template.schema.json) — the template itself.
- [`wb-mqtt-serial-confed-common.schema.json`](https://github.com/wirenboard/wb-mqtt-serial/blob/master/wb-mqtt-serial-confed-common.schema.json) — shared definitions. The template's `$ref`s point here (channel fields, `on_value`, address formats, etc.). **The per-field contract lives here — read it; don't rely on memory.**

## Validate

Use `scripts/validate.py` (Draft7, merges both schemas, strips the `//` comments). The driver schemas contain `//` comments, so a plain `json.load` on them fails. A `.json.jinja` template is rendered to JSON first (Jinja is validated as the rendered result — the same the driver/CI see).

## Read the enums live — don't hardcode them

The closed enums (`reg_type`, `format`, `type`/control, `word_order`, `byte_order`) live in the schema `definitions` and **grow over time**. Never freeze a copy in prose or code — the drift between a hardcoded list and the schema is the main source of false "invalid value" findings. Pull the current values from the schema (the same file `validate.py` fetches):

```bash
uv run --with jsonschema python3 - <<'PY'
import json, re
raw = open("wb-mqtt-serial-confed-common.schema.json").read()
defs = json.loads(re.sub(r'(?<!["\w:])//[^\n]*', '', raw))["definitions"]
for k in ("reg_type", "format", "word_order", "byte_order", "control_type"):
    print(k, "=", defs.get(k, {}).get("enum"))
PY
```

`control_type` is the channel `type` enum. It includes many `reg_type` values you might not recognise (`press_counter`, `holding_single`/`holding_multi`, `obis_*`, …) — they are valid; verify against this output, not from memory.

## What a template contains (navigation only)

Top level is small: `device_type` and `device` are the load-bearing keys (`title`/`group` usually present too). Inside `device`: `channels[]`, optional `parameters[]` (firmware settings), `groups[]` (UI grouping), `translations`. The exact required/optional set and every field's contract are defined in the schema — let `validate.py` report them rather than trusting a hand-copied list.

`device` is an `anyOf` in the schema ("device with channels" OR "subdevice with `protocol`"). Because of that, a raw Draft7 message often complains about the wrong branch — `validate.py` picks the nearest branch and shows the concrete leaf errors instead.

## What the schema does NOT catch

The schema is format only. Unit values "from the table", deprecated types, text style — layer 2 (`wb-standard.md`). Equal `enum`/`enum_titles` lengths, condition semantics, endianness behaviour — layer 3 (`driver-behavior.md`). Valid-against-schema ≠ correct per standard/driver.
