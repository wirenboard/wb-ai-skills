# Translations & naming — templates and json-editor schemas

How to name config keys, translation keys and enum values so the raw JSON stays readable and the UI stays translatable. The base convention is documented in the `wb-mqtt-serial` README: a translation entry is `"<lang>": "<English string>": "<translation>"` — **the displayed English text is the key by default**; synthetic keys are the exception, not the rule.

## Device templates (`wb-mqtt-serial`) — what serves as the translation key

| Text | Key style | Example |
|------|-----------|---------|
| Template `title` | synthetic key; for new templates use the canonical form `<MODEL>_template_title` (factory templates vary in style) | `WB-MXXX_template_title` |
| Channel names, group titles, `enum_titles` | English text **is** the key | `"Uptime"`, `"HW Info"` |
| Parameter title / description | English text is the key **by default**; a synthetic key (`<param_id>_title` / `<param_id>_description`) only for long descriptions or strings shared across templates | `"Baud rate"`; long: `baud_rate_description` |

Rules:

- **Both `en` and `ru` sections are present.**
- `en` holds entries only where the displayed text differs from the key: `"Uptime": "Uptime (s)"`. Short English labels that display as-is need no `en` entry.
- In **new** templates `ru` translates everything: template title, group titles, channel names, parameter titles/descriptions, `enum_titles`. Existing factory templates vary (some translate only the title) — don't copy their gaps.
- Capitalization: EN — Each Word Capitalized (`Board Temperature`); RU — только первое слово с большой (`Температура платы`); abbreviations (`VOC`, `MQTT`, `RAM`) always caps in both.

```json
"translations": {
  "en": {
    "WB-MXXX_template_title": "WB-MXXX (2-channel relay module)",
    "Uptime": "Uptime (s)"
  },
  "ru": {
    "WB-MXXX_template_title": "WB-MXXX (2-канальный модуль реле)",
    "HW Info": "Данные модуля",
    "Uptime": "Время работы (с)"
  }
}
```

## json-editor / confed schemas (custom drivers, config editors)

JSON schemas rendered by the web UI (confed / json-editor) follow the **same convention** as device templates: titles and labels are English text, `translations.ru` maps English → Russian (factory example: `wb-mqtt-mbgate.schema.json` — `"Enabled"`, `"Modbus unit ID"` as keys). Synthetic keys are used for the schema root title/description and for long or shared strings, where they keep diffs small and make the en/ru pair explicit:

```json
"description": "device_config_description",
"translations": {
  "en": {"device_config_description": "Long description of what this configuration page controls."},
  "ru": {"device_config_description": "Длинное описание того, чем управляет эта страница настроек."}
}
```

## Naming coherence — the chain check

For every field walk the chain **config key ↔ translation key ↔ enum value ↔ displayed text**. All four must tell the same story. Acceptance test: reading the raw config *without* the schema, you can guess what is selected in the editor.

- **An enum value reads like its label.** Value `night_mode` under the label "Night Mode" — good. Value `mode_2` under "Night Mode" — fails the test: nobody reading the config guesses what the editor shows.
- **A field name matches its label's meaning.** A field named `sleep_delay_s` labelled "Backlight Off Delay" leaves the config reader unsure it is the same setting. Align them: rename the field to `backlight_off_delay_s`, or relabel to "Sleep Delay".
- **Translation keys derive from the config key.** Parameter `work_mode` with value `night_mode` → key `work_mode_night_mode`; parameter `in0_mode` → keys `in0_mode_title`, `in0_mode_description`. If a key shares no stem with its config key (parameter `in0_mode`, key `first_input_title`), you can't find the parameter from the key or the key from the parameter — rename the key.
- **Internal names (`definitions.*`, `$ref` targets) match the page vocabulary.** A definition named `module` on a page that calls the thing "Sensor" should be `sensor`.

These mismatches are invisible in the UI (the label renders fine) and surface only when someone reads or edits the raw config — which is exactly when they are most confusing. Check the chain before shipping, not after.
