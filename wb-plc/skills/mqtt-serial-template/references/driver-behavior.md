# driver-behavior — layer 3: driver behaviour (not expressible in the schema)

Rules that the JSON Schema **cannot express** but that wb-mqtt-serial actually requires or does. This is the skill's own knowledge — it is not in the schema or the written standard. Valid-against-schema ≠ correct for the driver. Verify against the [wb-mqtt-serial](https://github.com/wirenboard/wb-mqtt-serial) sources (C++) when in doubt.

## `enum` and `enum_titles` — equal length (blocker)

`enum` (values) and `enum_titles` (per-language labels) are parallel arrays. Different lengths → the driver loses labels / behaves unpredictably. **Blocker.** The schema does not check the lengths — check by hand (both in `channels` and in `parameters`).

## `condition` pairs sharing an address — normal, NOT a duplicate

A valid pattern: two (or more) channels with the **same `address`** and **mutually exclusive `condition`** (usually on firmware version `fw` or on a parameter value). Only one is active in MQTT at a time. **Do not treat this as a duplicate address and do not collapse them.**

- `condition` is an expression over **`parameters`** (a parameter `id`), e.g. `"condition": "in0_mode==3"`. It may reference parameters only, not other channels.
- Consequence: `id`/`name` in a template are **not unique** — condition-gated twins legitimately coincide. When matching registers for a bulk edit, match by position, not by `id`.

## `name` is the MQTT topic id — effectively immutable

A channel's `name` is the MQTT control id (the topic segment) **and its only identifier** — a channel has no separate `id` field; `id` is for parameters and groups, not channels (WB-STD-003 §7.1: the channel is named by `name` alone). Don't add an `id` to a channel. Changing `name` renames the topic and **breaks existing rules/integrations**. To rename a channel for the user, add a `translations` entry (`en`/`ru`) that maps the `name` to a display string — leave `name` itself unchanged. (This is the WB-STD-001 stance on topic identifiers; see `wb-standard.md`.) So `name` is **not** a freely editable field — see frozen fields below.

Example — to change what a channel reports (aggregated vs instantaneous): keep the existing channel's `name`, relabel it (e.g. `… aggr`) via `translations`, and add a **new** channel with a new `name` for the new value (e.g. `… inst`). Renaming via `translations` keeps the MQTT topic unchanged.

**Golden-file check — templates that live in the `wb-mqtt-serial` repo.** `test/TDeviceTemplatesTest.Validate.dat` captures every shipped template's expected output. When you edit **existing** channels, that file **must not change** — a non-empty `git diff` on it means you altered observable output (usually a `name`), which is exactly the regression this rule guards against. Adding **new** channels is different and expected to change it: the file legitimately gains records for the new channels. (Standalone / community templates aren't in that repo, so this check doesn't apply to them.)

## Endianness — big-endian by default

Modbus is byte big-endian. For multi-register values (`u32`/`s32`/`float`/`double`) some manufacturers use little-endian **word** order. The driver assumes `word_order: "big_endian"` by default. Symptom of a wrong choice: the value "jumps"/is absurd → try `"word_order": "little_endian"` (rarely `byte_order`). This is confirmed on hardware (`/wb-serial`), not derivable from the schema.

## Fields defined in the schema but easy to get wrong

These fields **are** in the schema (`confed-common`) — read the contract there; noted here only for the behavioural gotcha:

- **String length** — `format: "string"` needs `size` (register count); without it the length is undefined.
- **Bit field** — an address suffix `"<reg>:<offset>:<width>"` extracts bits; a single register is just a number/hex.
- **`pushbutton` / write-only** — a button that writes a value uses `on_value`; there is no `value` field on a channel, so a button with `value` **silently no-ops**. A write-only command puts its address in `write_address`. `wo-switch` is treated by the driver as **forced write-only** (state isn't read) — expected, not a bug.

## `reg_type` — trust the schema enum

Many "unfamiliar" `reg_type` values are **valid** (`press_counter`, `relay`, `power`, `holding_single`/`holding_multi`, `obis_*`, and more — the schema has ~50). Do not flag them from memory — check the live enum (`schema-reference.md`).

## Frozen fields when editing (Hard rule 2)

When editing a template, touch **only** what the finding names. These fields determine how the device is polled; editing them "in passing" breaks operation and requires cross-checking the manufacturer register map plus sign-off:

> `address`, `reg_type`, `format`, `scale`, `offset`, `enum` (values), `condition` logic, and `name` (topic id — see above).

Safe to edit without a hardware cross-check: `translations`, `group`, descriptions/texts, and `units` (as part of migrating a deprecated `type`). Re-run `scripts/validate.py` after any edit.
