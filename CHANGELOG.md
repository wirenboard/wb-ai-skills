# CHANGELOG

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версионирование — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

## [0.1.0] — 2026-05-07

Первый публичный релиз. Тестировано на A25NDEMJ (wb7, wb-2410/wb-2602) и A2V6W7I6 (wb8, wb-2507).

### MCP-сервер

**43 типизированных tool в 11 группах**, реализованных через стандартный MCP (`@modelcontextprotocol/sdk`) на Bun:

- **Discovery (3):** `wb_discover` (mDNS + ручные), `wb_probe`, `wb_add_controller`.
- **SSH+файлы (4):** `wb_ssh_exec`, `wb_ssh_exec_async`, `wb_read_file`, `wb_write_file`.
- **Async jobs (3):** `wb_job_status`, `wb_job_tail`, `wb_job_cancel`. Через `systemd-run --collect` + script-file (`/mnt/data/ai/wb-ai-integration/jobs/<id>.sh`) + `StandardOutput=append:`. Переживает разрыв SSH, gc по 24-часовому TTL.
- **MQTT (4):** `wb_mqtt_read` (любой топик, не только WB), `wb_mqtt_write` (с опц. `retain`/`qos`), `wb_mqtt_list`, `wb_mqtt_rpc`.
- **MQTT-устройства (3):** `wb_mqtt_devices`, `wb_mqtt_controls`, `wb_mqtt_inventory` — сводно: id+driver+error+controls с распакованным meta и error-флагами по [WB Conventions](https://github.com/wirenboard/conventions) (`r`/`w`/`p`).
- **Confed (2):** `wb_confed_load`, `wb_confed_save`. Принимает content как объект **или** JSON-строку (автопарсит — иначе confed запишет escape-нутую строку и сломает конфиг).
- **wb-rules (5):** `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_disable` (через `Editor/ChangeState`), `wb_rules_delete` (через `Editor/Remove`).
- **History (2):** `wb_history`, `wb_history_chart` — Vega-Lite SVG (line/bar/area/point/histogram/heatmap/boxplot) с 1/2/3+ unit-стратегиями (одна шкала / двойная Y-ось / нормализация в [0;1]).
- **Audit/state (3):** `wb_audit` (release парсится в объект), `wb_state_save`, `wb_state_diff`.
- **Modbus/serial (6):** `wb_modbus_template` (через RPC `config/Load.types` → mqtt-id → файл шаблона; `view=summary/full/channels-only/meta-only`, `enabledOnly`, `channelFilter`), `wb_modbus_templates_list` (без filter — сводка по группам, с filter — flat list, регистронезависимо), `wb_modbus_device_info` (параметры прошивки fw/model/parameters), `wb_modbus_probe`, `wb_modbus_ports`, `wb_modbus_scan` (через `wb-device-manager/bus-scan/Start`, async, extended Fast Modbus + standard fallback; auto-detect портов и baud), `wb_modbus_add_devices` (auto-add найденного сканером с `dryRun`).
- **Diagnostics (7):** `wb_metrics`, `wb_logs` (с `since`/`until`/`grep`/`grepInvert`), `wb_failed`, `wb_serial_debug` (atomic enable→collect→disable через `trap restore_off`), `wb_systemd_unit` (status/start/stop/restart/enable/disable/mask/unmask/cat/list-deps), `wb_network_status` (interfaces+nm+ping), `wb_cloud_status` (сервис+cert+MQTT-controls).

### Скиллы

**21 bash-скилл** + **19 mcp-скиллов**:
- Общий доменный стек: `wiren-board`, `wb-mqtt-serial`, `serial-templates`, `wb-rules`, `scenarios`, `notifications`, `troubleshooting`, `troubleshooting-serial`, `services`, `network`, `wb-cloud`, `mqtt-broker`, `controller-backup`, `controller-update`, `hardware-modules`, `software-install`, `zigbee`, `history`, `bugreport`.
- Только bash (не зависит от контроллера): `diagrams` (Mermaid), `documentation-search` (поиск по wiki/GitHub).
- Совместимы с Claude Code и opencode (через `install-skills.sh`).

### Архитектурные решения

- **SSH host-key:** `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null` — переживает factory reset и FIT-прошивку без `ssh-keygen -R`.
- **Никаких внешних SQLite/npm-биндингов:** MCP-сервер использует только `@modelcontextprotocol/sdk`, `zod`, `vega`, `vega-lite`. Состояние — JSON-файлы в `~/.wb-mcp/`.
- **MQTT через системные утилиты:** `mosquitto_sub -F '%t\t%p'` (TAB-разделитель — корректный парсинг имён контролов с пробелами типа `Input 0`, `Input 0 counter`).
- **Безопасность:** валидация invalid wildcards (`+` внутри уровня MQTT-топика), валидация jobId regex, защита от shell-инъекции через `shellQuote`.

### Ключевые архитектурные решения и пойманные доменные баги

В процессе разработки и тестирования на живых контроллерах поймано и исправлено около двух десятков ошибок — доменных (несоответствие реальному поведению WB-стека) и интеграционных (shell-quoting, async-jobs, MQTT-парсинг). Из заметного:

- **audit**: парсер `===WB-AUDIT===<name>` ломался при `cat` файла без trailing `\n` — фикс через `printf "\n===…\n"`.
- **mqtt-controls**: `mosquitto_sub -v` резал имена контролов с пробелами по первому пробелу — фикс через TAB-разделитель (`-F '%t\t%p'`).
- **async jobs**: `bash -c 'CMD > LOG'` редиректил только последнюю команду из цепочки `;` — фикс через script-file + `StandardOutput=append:`.
- **confed_save**: content как строка ломал конфиг (escape-quoted JSON) — добавлен `JSON.parse` для строк.
- **rules_save/load**: абсолютный путь интерпретировался RPC как относительный → создавал файл в `/etc/wb-rules/etc/wb-rules/` — фикс через relative path.
- **modbus_scan**: `wb-mqtt-serial/port/Scan` молча пропускал живые WB-устройства (наблюдалось на WB-MAP6S) — переход на `wb-device-manager/bus-scan/Start`.
- **modbus_template**: скан 250+ файлов через jq падал по timeout — переход на mapping через RPC `config/Load.types`.

[Unreleased]: https://github.com/wirenboard/wb-ai-integration/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/wirenboard/wb-ai-integration/releases/tag/v0.1.0
