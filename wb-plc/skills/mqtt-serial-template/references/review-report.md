# review-report — review mode: audit a template (read-only)

Triggered by "check / review / audit this template against the schema and standard". **Writes nothing** — reads and reports only. Fixes, if wanted, are a separate explicit request (then it's edit mode; frozen fields — `driver-behavior.md`).

Criteria are the same three layers as authoring. This file does not restate the rules (the sources are `schema-reference.md` / `wb-standard.md` / `driver-behavior.md`); it gives the **procedure** to check a finished file and the **report format**.

## Input

Path to `config-<device>.json` (local / GitHub raw / PR number) — a file on a branch not yet merged to `main` is fine. If the manufacturer register map is available, use it as the arbiter for `address`/`scale`/`format` (the template may be wrong).

## Procedure

1. **JSON syntax.** Parse it (allow the `//` comments found in WB sources). Trailing comma / duplicate keys → **blocker** (won't load).
2. **Layer 1 — schema.** `uv run <skill>/scripts/validate.py <file>` (for a fixed version, `--ref`/`--schema-dir`). A schema error is normally a **blocker** (the driver won't load it) — *but the schema can be stricter than the driver, which normalizes some fields before it validates.* So a shipped template in `wb-mqtt-serial/templates/` can legitimately do something the raw schema rejects; don't 🔴 the author for that, and don't push a "fix" to a frozen field just to satisfy a stricter-than-reality schema. Known case: **integer channel `enum`** — the schema declares channel enum items as `string`, but the driver converts numeric channel enums to strings on load (`FixChannelsEnum`), so `enum: [0, 1, 2]` loads fine. `validate.py` applies the same normalization, so it won't flag it either. Prefer string enums in **new** templates (matches the schema and the confed custom-channel editor); leave existing integer enums as-is (frozen values). A template marked `deprecated: true` is exempt — the driver skips schema-validating it (it may be broken against the latest schema), so schema drift there is **not** a blocker (`validate.py` still checks it but labels it deprecated).
3. **Layer 2 — standard** (`wb-standard.md` → the sources): topic names, **canonical names** (a service channel / standard group with a registry id must use it — `uptime` not `up_time`, `g_hw_info` not `g_service`; alternative forms are a finding — WB-STD-001 §6, WB-STD-003 App. А/Б), `units` values, deprecated control types (blocker), text style, `translations` en/ru; no `slave_id`/`baudrate` channels (WB practice — `authoring-workflow.md` §4, not in the written standard).
4. **Layer 3 — driver** (`driver-behavior.md`): equal `enum`/`enum_titles` lengths; condition pairs sharing an address (normal — do **not** flag as a duplicate); `condition` references parameters only; `pushbutton` uses `on_value`/`write_address`; `name` unchanged (renames via `translations`); sane `word_order` for multi-register values.

For every item — a **✓ / ✗ / ⚠** verdict with **evidence** (field name, channel index, snippet). Don't assume — show it.

## Classification

- **🔴 Blockers** — won't load or is incorrect for the driver: invalid JSON, schema error (layer 1 — unless it's a stricter-than-driver case the driver normalizes, see Procedure 2), deprecated control type, `enum`/`enum_titles` mismatch, unit not from the table, `slave_id`/`baudrate` registers.
- **🟡 Recommendations** — style / completeness / minimalism: translation casing, punctuation/typography, missing `groups` with many channels, raw `device.name`, redundant channels.

(Which side of the line each rule falls on is defined by its source — see the layer references.)

## Report format

1. **Short summary** — what was checked, overall verdict, schema/standard version (stamp commit/ref — `main` floats).
2. **Action items** — visually separated into 🔴 Blockers / 🟡 Recommendations.
3. **Detailed pass** across layers 1/2/3: each item with ✓/✗/⚠ and evidence.
4. Before delivery — self-check: every ✗/⚠ is backed by a concrete fragment of the artifact, not a guess.

## Boundary with publication

Here — an audit of the **template itself** (three layers). Auditing the **publication** of a template (wiki page, PR shape into `wb-community`) is out of scope.
