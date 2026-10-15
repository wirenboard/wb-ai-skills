# wb-standard — layer 2: the WB standard and conventions

The source of truth for **conventions** (names, units, control types, text style). Some are blockers, some recommendations.

This file is a **map to the sources, not a copy of the rules.** The rules already live — and change — in the standard and the conventions; restating them here would only drift. Read them at the source.

## Sources

- [wirenboard/conventions](https://github.com/wirenboard/conventions) — README sections **Naming**, **Controls**, **`#### Units`**. Prose, no machine linter.
- [wirenboard/wb-standards](https://github.com/wirenboard/wb-standards) (public, CC BY 4.0): **WB-STD-001** (MQTT topic identifiers), **WB-STD-002** (UI text style), **WB-STD-003** (wb-mqtt-serial templates; references 001/002 and `confed-common`). Which documents to feed for which task — the package README table [«Что подавать AI-агенту»](https://github.com/wirenboard/wb-standards#что-подавать-ai-агенту). Refer to the documents by their WB-STD codes, not by file names — files may be renamed.

## Which source governs which concern

| Concern in the template | Read this |
|---|---|
| Channel `name` (MQTT topic id): allowed characters, snake_case, word count | WB-STD-001 + conventions **Naming** (the forbidden-character set is also the schema `channel_name` pattern — layer 1) |
| **Canonical names** — a channel/group for a concept in the WB registry must use the registry id; alternative forms are **not allowed** (§4.5). Blocker-adjacent | channels (service, I/O, counters, 3-phase, climate, alarms) → **WB-STD-001 §6** / WB-STD-003 **App. Б**; standard groups/subgroups (`g_general`, `g_hw_info`, `g_debug`, `g_in<N>`, `g_outputs`, `g_safety`, `gg_in<N>_*`) → WB-STD-003 **App. А** |
| `units` value (must be from the unit table, latin, `deg C` not `°C`, …) | conventions **`#### Units`** |
| Control `type`: which are deprecated, what to migrate to | conventions **Controls** (the deprecation warning + the current deprecated set) |
| `title` / `description` / `translations` text style (casing, abbreviations, punctuation, decimal separator) | WB-STD-002 |
| `translations` **key** style (identifier-as-key; keys `<id>` / `<id>_description` / `<id>_enum_<N>`) | WB-STD-003 §4.3 (see `i18n-naming.md` for the pointer) |
| name ↔ key ↔ enum ↔ label coherence | `i18n-naming.md` (WB value-add, not in the written standard) |
| Template structure conventions (grouping; `device.name` — the literal device marking, untranslated, any characters) | WB-STD-003 |
| No `slave_id`/`baudrate` channels or parameters (communication settings live in the UI, not in the template) | WB practice — `authoring-workflow.md` §4; not in the written standard |
| Template lifecycle & versioning: backward-compat (channels/params are append-only — never change or delete an existing `id`/`name`, only add), `fw` + `hw[]` firmware binding, `-fw<N.M>` / `-deprecated` templates, `enabled:false` for channels added to a shipped template | WB-STD-003 §9.4, §10 |

## Working rules (procedure, not restated content)

- **Sync with the live section.** `#### Units` and the deprecated-controls set grow. Open the current README/standard at work time — do not rely on a snapshot.
- **Pin the version in the verdict.** `main` floats — when you report "checked against the standard", stamp the source version/commit so a template that passed before but fails now can be explained.
- **Deprecated control type → blocker** (not a recommendation): future wb-mqtt-serial versions may drop support. Check both `channels` and `parameters`.
- **Unit not in the table** (e.g. `kW`/`kVA`/`mWh`): don't invent one. Either use an existing unit (and recompute `scale`), or — if a new unit is genuinely needed — add it to the convention **first**, then use it. The process (confirm with the user before starting): one PR to [wirenboard/conventions](https://github.com/wirenboard/conventions) (add to the Units table + changelog + version bump), one PR to [wirenboard/homeui](https://github.com/wirenboard/homeui) (unit translations — `ru` always, `en` only if the unit has special characters — + changelog bump); use the unit in a template only after **both** are merged.

## Boundary with consumer skills

This is the canonical technical layer. Skills that build on templates layer their own rules on top and point here for the rules above instead of duplicating them.
