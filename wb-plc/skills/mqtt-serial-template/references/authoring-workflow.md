# authoring-workflow — develop mode: documentation → valid template

Create a new wb-mqtt-serial template **without a controller** — from documentation to valid JSON. On-bus testing and adding the device belong to `/wb-serial` (see "Hand off to /wb-serial").

## 0. Register map (don't start without it)

`WebFetch`/read the manufacturer manual: the register table (addresses, register type, format, scale, endianness, enum values). **Guessing = endless debugging** — if there's no map, ask the user. Confirm the target driver version if it matters (it selects the schema for `validate.py --ref`).

## 1. Start from a similar template

The upstream catalogue is the source of examples and idioms: `https://github.com/wirenboard/wb-mqtt-serial/tree/master/templates` (`config-<device>.json.jinja`). Open 1–2 similar ones (same class: meter / relay / sensor) and follow their shape instead of inventing one.

**Jinja templates.** WB's own templates are mostly `.json.jinja`: Jinja `{% for %}` loops generate repetitive channels, and `{% include %}` composes a multi-module device from single-module templates (e.g. `config-wb-mcm8.json.jinja`). The driver, CI and `validate.py` all work on the **rendered** JSON — `validate.py` renders a `.jinja` file before validating. In the wb-mqtt-serial repo, regenerate the golden template test after adding channels: `make dump-templates` (see WB-STD-003 §10).

## 2. Minimal skeleton + first validation

Build the minimum and validate against the schema early — structural mistakes surface fast:

```json
{ "title": "acme_em100_template_title", "device_type": "acme-em100", "group": "g_energy_meters",
  "device": { "name": "ACME EM-100", "id": "acme_em100",
    "channels": [ { "name": "voltage", "reg_type": "input", "address": 0,
                    "format": "u16", "scale": 0.1, "type": "value", "units": "V" } ] } }
```

Identifiers (WB-STD-003 §4.4): `device_type` **equals the file basename** — lowercase `[a-z0-9._-]`,
usually hyphens (`acme-em100` ↔ `config-acme-em100.json`; dots appear in `-fw<N.M>` suffixes), so it
isn't snake_case. `device.id` **is** snake_case per WB-STD-001 (`acme_em100`, `[a-z0-9_]`); the MQTT
device id defaults to `<device.id>_<slave_id>`. `device.name` is the literal device marking
(`ACME EM-100`) — untranslated, any characters. `title` is a translation key
(`<id>_template_title`). Don't mix the three.

```bash
uv run <skill>/scripts/validate.py config-acme-em100.json    # layer 1
```

## 3. Expand the channels

From the register map, one class at a time:

- **Channel `name` — canonical id first.** If the register is a service channel, digital/analog I/O, press counter, three-phase electrical, climate or alarm, it has a **canonical id** — use it (`uptime` not `up_time`, `v_vin` not `input_voltage`): WB-STD-001 §6 / WB-STD-003 App. Б. Alternative forms are **not allowed** (WB-STD-003 §4.5). Only coin a fresh snake_case id (per WB-STD-001) for a genuinely device-specific channel with no canonical form.
- `reg_type` by Modbus function (FC1 `coil` RW, FC2 `discrete` RO, FC3 `holding` RW, FC4 `input` RO); protocol-specific values come from the schema enum.
- `format`/`scale`/`offset` from the map. Multi-register values → mind `word_order` (big-endian by default; see `driver-behavior.md`).
- `type`, `units`, deprecated types, text style — the rules and current lists live in the sources; see `wb-standard.md` (don't hardcode them). Measurement channels are `value` + `units`, never a deprecated measurement type.
- `enum` + `enum_titles` — equal length (`driver-behavior.md`).
- **Adding channels to an existing/shipped template: mark the new channels `"enabled": false`.** Opt-in — a template update must not increase bus polling for existing users; whoever needs a channel enables it in the UI. (For a brand-new template, choose what ships enabled.)

## 4. `parameters` and `groups`

- `parameters` — firmware settings (`id`/`address`/`reg_type`/`enum`/`enum_titles`/`default`). A channel `condition` may reference them.
- `groups` — logical grouping; the "when to group" convention is in the standard (`wb-standard.md`). Use the canonical group ids where a concept already has one (`g_general`, `g_hw_info`, `g_debug`, `g_in<N>`, `g_outputs`, `g_safety`, subgroups `gg_in<N>_*` — WB-STD-003 App. А); don't coin a `g_service`-style variant for one that exists.
- Do **not** add channels for `slave_id`/`baudrate` (UI-configured, not template) or unneeded `enabled:false` noise.

## 5. Translations and style

Add `translations` (en/ru) for `title`, groups, channels, `enum_titles`. The casing/style rules are in WB-STD-002 (`wb-standard.md`) — apply them from there.

## 6. Final pass

`scripts/validate.py` (layer 1) + a walk through layers 2/3 → clean copy. Full audit with a report — `review-report.md`.

## Hand off to /wb-serial (on-hardware testing)

This skill produces a **correct file**; verifying "how it behaves on a real bus" is out of scope. Hand to the user / `/wb-serial` for:

- adding the device to `/etc/wb-mqtt-serial.conf` (`add-devices`) and checking channels actually publish;
- confirming `word_order`/`format`/`scale` against real values (value "jumps" → fix endianness);
- reading/writing `parameters` (`fw-params`), bus scan, CRC/timeout diagnostics.

Edits from testing come back here (edit mode; frozen fields — `driver-behavior.md`).
