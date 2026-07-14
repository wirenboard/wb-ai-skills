# Translations & naming — templates and json-editor schemas

How to name config keys, translation keys and enum values so the raw JSON stays readable and the UI stays translatable. Conventions distilled from factory `wb-mqtt-serial` templates (reference example: `config-wb-m1w2.json`).

## Device templates (`wb-mqtt-serial`) — what serves as the translation key

| Text | Key style | Example |
|------|-----------|---------|
| Template `title` | synthetic key `<MODEL>_template_title` | `WB-M1W2_template_title` |
| Parameter title / description | synthetic key `<param_id>_title` / `<param_id>_description` | `temperature_readings_filter_deg_title` |
| Channel names, group titles, `enum_titles` | English text **is** the key | `"Uptime"`, `"HW Info"` |

Rules:

- **Both `en` and `ru` sections are present.**
- `en` holds entries only where the displayed text differs from the key: `"Uptime": "Uptime (s)"`. Short English labels that display as-is need no `en` entry.
- `ru` translates everything: template title, group titles, channel names, parameter titles/descriptions, `enum_titles`.
- Capitalization: EN — Each Word Capitalized (`Board Temperature`); RU — только первое слово с большой (`Температура платы`); abbreviations (`VOC`, `MQTT`, `RAM`) always caps in both.

```json
"translations": {
  "en": {
    "WB-M1W2_template_title": "WB-M1W2 (2-channel temperature measurement module)",
    "Uptime": "Uptime (s)"
  },
  "ru": {
    "WB-M1W2_template_title": "WB-M1W2 (2-канальный преобразователь для термометров 1-Wire)",
    "HW Info": "Данные модуля",
    "Uptime": "Время работы (с)"
  }
}
```

## json-editor / confed schemas (custom drivers, config editors)

For JSON schemas rendered by the web UI (confed / json-editor) the standard is stricter: **every UI string is a synthetic key**, never raw English text, and `translations` carries both `en` and `ru`:

```json
"title": "device_config_title",
"translations": {
  "en": {"device_config_title": "Actuator Configuration"},
  "ru": {"device_config_title": "Настройка привода"}
}
```

Rationale: schema strings (titles, descriptions, enum labels, group headers) are longer and change more often than template channel names; a synthetic key keeps diffs small and makes the en/ru pair explicit.

## Naming coherence — the chain check

For every field walk the chain **config key ↔ translation key ↔ enum value ↔ displayed text**. All four must tell the same story. Acceptance test: reading the raw config *without* the schema, you can guess what is selected in the editor.

- **An enum value reads like its label.** Value `widget_command` under the label "Widget Command" — good. Value `bus_command` under "Widget Command" — fails the test: nobody reading the config guesses what the editor shows.
- **A field name matches its label's meaning.** `liveness_interval_ms` labelled "Connection Check Interval" — rename one of them (either `connection_check_interval_ms`, or a "Liveness ..." label).
- **Translation keys derive from the config key.** Parameter `learning_type` with value `widget_command` → key `learning_type_widget_command`; parameter `in0_mode` → `in0_mode_title`. A translation key that shares no stem with its config key is a smell.
- **Internal names (`definitions.*`, `$ref` targets) match the page vocabulary.** A definition named `device` on a page that calls the thing "Actuator" should be `actuator`.

These mismatches are invisible in the UI (the label renders fine) and surface only when someone reads or edits the raw config — which is exactly when they are most confusing. Check the chain before shipping, not after.
