# i18n-naming — layer 2: translation keys and naming coherence

Translation-key style is defined by the standard (WB-STD-003 §4.3) — this file points there
for it and adds the one thing the standard does **not** spell out: the config↔label coherence
check reviewers otherwise carry in their heads. Casing is WB-STD-002 (see `wb-standard.md`).

## Translation-key style → WB-STD-003 §4.3

Read the rules there; don't restate them. The model is **identifier-as-key**: the display
field holds a snake_case identifier, and both languages live in `translations` keyed by that
identifier — never the English text written inline as the key.

- Where the identifier lives: channel → `name` (no `id`, see `driver-behavior.md`);
  parameter / group → `id`, duplicated into the **required** `title` field that serves as
  the translation key (`title` = `id`); template catalogue name → the top-level `title`.
- `device.name` is **not** part of the model: it is the literal device marking — one
  untranslated string for all languages, any characters allowed, including Cyrillic
  (WB-STD-003 §4.4). Don't add translations for it and don't flag it as a non-key string.
- Key patterns: `<id>` (the entity's main text), `<id>_title`, `<id>_description`,
  `<id>_enum_<N>` (index from 0). Both `en` and `ru` are given explicitly — a missing
  translation renders the raw key in the UI.
- Example: group `{"id": "g_general", "title": "g_general"}` with
  `translations.en["g_general"] = "General"`, `translations.ru["g_general"] = "Общее"`.

The older **"English-string-as-key"** model — the English text serving as both key and text
(`"Uptime": …`) — is **retired**: changing the English text broke the link to the Russian
translation. Even short labels go through an identifier (`g_general` →
`{en: "General", ru: "Общее"}`, not the bare string `"General"`).

Retired for **new** work — WB-STD-003 §1 keeps existing templates on a separate migration
plan. So in **review/edit** don't rewrite a legacy channel's English-string `name`/key to the
new model as a drive-by: a channel's `name` is its MQTT topic (frozen field —
`driver-behavior.md`), and changing it breaks the topic and the golden file. Migrate a legacy
template only under the migration plan, never as review churn.

## Naming coherence — the chain (value-add, not in the standard)

For every entity walk the chain **identifier ↔ translation key ↔ enum value ↔ displayed
text**; all must tell the same story. Acceptance test: reading the raw config *without* the
schema, you can still guess what is selected in the editor.

- **An enum value reads as its label.** Value `night_mode` ↔ label "Night Mode" — good;
  `mode_2` ↔ "Night Mode" — a config-readability blocker.
- **A name matches the label's meaning.** Field `sleep_delay_s` with label "Backlight Off
  Delay" — the config reader can't tell they are the same thing. Bring them to one meaning:
  rename the field to `backlight_off_delay_s`, or change the label to "Sleep Delay".
- **The translation key is the entity's identifier** (`in0_mode` → `in0_mode`,
  `in0_mode_description`). A key with no shared root with the id (param `in0_mode`, key
  `first_input_description`) can't be traced back either way — rename it.

These mismatches are invisible in the UI (the label renders fine) and surface only when
reading or editing the raw config — exactly when they mislead the most.
