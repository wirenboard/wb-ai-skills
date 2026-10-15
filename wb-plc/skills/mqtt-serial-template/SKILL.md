---
name: mqtt-serial-template
description: "Author, edit and review wb-mqtt-serial device templates (JSON) for Wiren Board against the driver JSON Schema and the WB standard/conventions. The authoritative entry point for template conformance — wb-serial defers here for the schema/standard layer. Use when the user writes / edits / validates / reviews a wb-mqtt-serial config-*.json; asks about reg_type / format / control type / address / condition / units / enum / enum_titles / word_order; says 'make a template for device X', 'check / review this template against the schema', 'why won't wb-mqtt-serial load this template'. NOT for live-controller work — adding a device, testing on hardware, Modbus/CRC/timeout diagnostics, add-devices, fw-params, bus scan (→ /wb-serial)."
allowed-tools: Bash Read Write Edit WebFetch WebSearch
---

# mqtt-serial-template — author and review wb-mqtt-serial templates

Work with JSON device templates for the [wb-mqtt-serial](https://github.com/wirenboard/wb-mqtt-serial) driver: create a new one from documentation, safely edit an existing one, review it against the schema and the WB standard. Three modes — **develop / edit / review** (Action map below).

This is the **authoritative entry point** for template conformance. The rules themselves live in their sources (schema, conventions, standard) — this skill does **not** restate them; it tells you where each rule lives, how to apply it, and adds the driver behaviour that those sources don't capture. `/wb-serial` points here instead of keeping its own copy.

## Three source-of-truth layers

The skill invents nothing — it checks against three live sources. Order = priority on conflict:

| Layer | Live source | What it governs | Finding class |
|---|---|---|---|
| **1. Format** | driver JSON Schema: [`wb-mqtt-serial-device-template.schema.json`](https://github.com/wirenboard/wb-mqtt-serial/blob/master/wb-mqtt-serial-device-template.schema.json) + `wb-mqtt-serial-confed-common.schema.json` | structure, enums (`reg_type`/`format`/`type`/`word_order`), patterns | **blocker** (driver won't load it) |
| **2. Standard** | [wirenboard/conventions](https://github.com/wirenboard/conventions) (Naming, Controls, `#### Units`) + [wirenboard/wb-standards](https://github.com/wirenboard/wb-standards) (WB-STD-001/002/003) | MQTT topic names, units, deprecated types, text style | blocker / recommendation |
| **3. Driver** | [wb-mqtt-serial](https://github.com/wirenboard/wb-mqtt-serial) sources (C++) | what the schema can't express: `enum`/`enum_titles` lengths, string width in the address, condition semantics, protocol-specific `reg_type` | blocker / recommendation |

🔑 **Read the source, don't trust memory.** The enums (`reg_type`, `format`, `type`/control), the `#### Units` table and the deprecated-types list are **live and grow**. Never hardcode or restate them — read them from the current schema/conventions at work time. The `references/` files describe *where* each rule lives and the layer-3 behaviour; they are not a copy of the rules.

## Quick Start — validate a template against the schema

```bash
# ${SKILL} = this skill's directory: <repo>/wb-plc/skills/mqtt-serial-template in a clone of
#            wb-ai-skills, /usr/share/wb-cli/skills/mqtt-serial-template on a controller.
# Standalone Draft7 validator: pulls template+confed-common schemas from upstream, merges
# them, strips // comments, prints errors. Does not need the generator running.
# uv installs deps itself (PEP 723); without uv — pip install jsonschema jinja2 && python3 …
uv run ${SKILL}/scripts/validate.py path/to/config-<device>.json
uv run ${SKILL}/scripts/validate.py path/to/config-<device>.json.jinja   # Jinja rendered first

# Offline / fixed driver version — local schemas or a specific tag:
uv run ${SKILL}/scripts/validate.py --schema-dir <dir-with-2-schemas> config-<device>.json
uv run ${SKILL}/scripts/validate.py --ref v2.259.0 config-<device>.json

# Reviewing many templates at once? There is no cache — each run re-fetches ~66 KB. Download
# the two schemas once and pass --schema-dir to the whole batch: faster, and it pins one
# schema version for the entire run.
```

Templates come in two forms — `config-<device>.json` and `config-<device>.json.jinja` (Jinja that renders to JSON; WB's own templates are mostly Jinja). `validate.py` renders a `.jinja` file first (includes resolved from its directory), then validates — the same rendered JSON the driver and CI check.

The schema catches layer 1 only (structure/enums/patterns). Layers 2 and 3 are **not** caught by it — go through them separately (`references/wb-standard.md`, `references/driver-behavior.md`). Full review procedure with a report — `references/review-report.md`.

## Hard rules — do not violate without explicit user OK

1. **Check the live source, not memory.** Before a verdict on `reg_type`/`format`/`type`/`units`/deprecated, read the value list from the **current** schema (`scripts/validate.py` or `WebFetch` the schema) and the live conventions section. Any list in `references/` may be stale.
2. **When editing, change only what the finding names.** Don't "tidy" `address`/`reg_type`/`format`/`scale`/`offset`/`enum`/`condition` along the way — editing them breaks how the device is polled. Frozen-fields rule — `references/driver-behavior.md`.
3. **`name` is the MQTT topic id — rename via `translations`, not by changing `name`.** Changing `name` breaks existing rules/integrations. See `references/driver-behavior.md`.
4. **`condition` pairs sharing an `address` are normal, not a duplicate.** Two channels with the same address and mutually exclusive `condition` (e.g. different firmware) is a valid pattern. Don't collapse them.
5. **`enum` and `enum_titles` must be the same length** — a mismatch is a blocker the schema does not catch. See `references/driver-behavior.md`.
6. **Deprecated control types are a blocker.** The live list lives in conventions (Controls); read it there, don't restate it. Migration is `type: "value"` + `units`.

## Action map (what you're usually asked for)

| User signal | Mode | Where |
|---|---|---|
| "make a template for device X", "add registers from the manual" | **develop** | `references/authoring-workflow.md` |
| "fix / add a channel / change units / translate" in an existing template | **edit** | `references/driver-behavior.md` (frozen fields) + layer 2 |
| "check / review / audit this template against the schema and standard" | **review** (read-only) | `references/review-report.md` |
| "why won't wb-mqtt-serial load this template" | review → layer 1 | `scripts/validate.py` + `references/schema-reference.md` |

## References

- `references/schema-reference.md` — layer 1: where things live in the schema, how to run Draft7, how to read enums live. **"Read the live schema."**
- `references/wb-standard.md` — layer 2: which conventions / WB-STD section governs each concern. A map to the sources, not a copy of the rules.
- `references/i18n-naming.md` — layer 2: points at WB-STD-003 §4.3 for translation-key style (identifier-as-key) and adds the config ↔ translation ↔ enum ↔ label coherence check the standard doesn't spell out.
- `references/driver-behavior.md` — layer 3: rules the schema can't express (`enum`/`enum_titles`, string width, condition pairs, `wo-switch`, big-endian default, frozen fields).
- `references/authoring-workflow.md` — develop mode: documentation → valid JSON **without a controller**; when to hand off to `/wb-serial` for on-hardware testing.
- `references/review-report.md` — review mode: audit procedure + report format (🔴 blockers / 🟡 recommendations).
- `scripts/validate.py` — standalone Draft7 validation (schema from upstream or local).

## What the agent does NOT do

- **Does not publish a template.** The PR into `wb-community`, the wiki page and other publication steps are out of scope. Here it's only the JSON itself (schema/standard correctness).
- **Does not touch a live controller.** Adding a device to `/etc/wb-mqtt-serial.conf`, on-hardware channel testing, `add-devices`, `fw-params`, bus scan, CRC/timeout diagnostics — that is `/wb-serial`. Here it's authoring/validating the file, not operating it.
- **Does not "silently fix" in review mode.** It finds and reports; fixes are a separate explicit request (then it's edit mode, Hard rule 2).
- **Does not change frozen fields** (`address`/`reg_type`/`format`/`scale`/`offset`/`enum`/`condition`) without checking the manufacturer register map and getting sign-off.

## When to ask the user

- **Register map.** No device documentation/addresses — don't guess (guessing = endless debugging). Ask for the manual / register map.
- **A unit not in the table.** A channel with `kW`/`kVA`/`mWh` that isn't in `#### Units` — confirm with the user (switch the unit and recompute `scale`, or keep it).
- **Ambiguous protocol / endianness.** If the docs don't make `word_order`/`format` clear for multi-register values — ask, or mark it as needing on-hardware verification (`/wb-serial`).
- **Target driver version.** If a fixed version matters (not upstream `master`) — ask which schema to use (`scripts/validate.py --schema-dir`/`--ref`).
