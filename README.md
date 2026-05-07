# wb-ai-integration

Интеграция [Claude Code](https://claude.ai/code) и [opencode](https://opencode.ai) с контроллерами [Wiren Board](https://wirenboard.com) — управление, диагностика, автоматизация по голосу и текстом.

Три компонента:

- **`mcp-server/`** — MCP-сервер на Bun с **43 типизированными инструментами** (`wb_*`): SSH, MQTT, MQTT-RPC, Modbus, mDNS-discovery, фоновые задачи через systemd, history+SVG-чарты, аудит, factoryreset-friendly хост-keys, сеть, облако, systemd-юниты. Подробности — [`mcp-server/README.md`](mcp-server/README.md).
- **`skills/bash/`** — **21 скилл** с Bash-рецептами (SSH + `mosquitto_*` + `avahi-browse` + `jq`). **Работают без MCP-сервера** — нужны только SSH-доступ и mDNS.
- **`skills/mcp/`** — **19 тонких скиллов**, маршрутизирующих интенты на `wb_*` tools MCP-сервера. Требуют запущенный `mcp-server`.

## Что выбрать

| Сценарий | Ставь |
|---------|-------|
| Хочется простой setup, MCP не готов / нет Bun | `skills/bash` |
| Уже есть Bun/Claude Code, хочется типизированные tools | `skills/mcp` + `mcp-server` |
| И то, и другое одновременно | **только один** — у `bash` и `mcp` совпадают `name:` во frontmatter |

`skills/bash` — источник доменных знаний (синтаксис wb-rules, формат RPC, шаблоны Modbus, разводка `meta/error` по WB Conventions). MCP-варианты ссылаются на bash для глубоких деталей и не дублируют их.

## Быстрый старт

См. [INSTALL.md](INSTALL.md) — отдельные пути для bash-only и mcp-flavor + типовые проблемы (mDNS, SSH-ключ, bun, opencode).

Минимальный путь для нетерпеливых:

```bash
git clone <repo> wb-ai-integration && cd wb-ai-integration

# Bash-flavor для Claude Code (без MCP-сервера, только SSH)
./install-skills.sh bash claude --global

# Или MCP-flavor (требует Bun + конфиг .mcp.json)
cd mcp-server && bun install && cd ..
./install-skills.sh mcp claude --global
```

Использование:

```
> /wiren-board
> найди контроллеры в сети, покажи их прошивки и метрики
> /wb-mqtt-serial
> просканируй шину на A25NDEMJ и добавь найденное в конфиг
```

## Скиллы

| Skill | Bash | MCP | Назначение |
|-------|:---:|:---:|------------|
| `wiren-board` | ✓ | ✓ | **Мастер**: SSH, MQTT, mDNS, безопасность, перекрёстные ссылки |
| `wb-mqtt-serial` | ✓ | ✓ | Modbus/RS-485, конфиг wb-mqtt-serial, включение каналов |
| `serial-templates` | ✓ | ✓ | Кастомные Modbus-шаблоны в `/etc/wb-mqtt-serial.conf.d/templates/` |
| `wb-rules` | ✓ | ✓ | JS-правила (ES5), виртуальные устройства, cron, alarms |
| `scenarios` | ✓ | ✓ | Декларативные Web UI сценарии (devicesControl/lightControl/thermostat/schedule) |
| `notifications` | ✓ | ✓ | Telegram bot setup, email через msmtp, SMS через mmcli, alarms.conf |
| `troubleshooting` | ✓ | ✓ | Общая диагностика (kernel mismatch, упавшие сервисы, диск, Docker) |
| `troubleshooting-serial` | ✓ | ✓ | RS-485 debug: CRC-ошибки, таймауты, raw-пакеты |
| `services` | ✓ | ✓ | systemd: override-conf, drop-ins, custom units/timers, mask/unmask |
| `network` | ✓ | ✓ | NetworkManager + wb-connection-manager: ethernet/wifi/4G/OpenVPN |
| `wb-cloud` | ✓ | ✓ | Wiren Board Cloud agent: активация, отвязка, свой backend |
| `mqtt-broker` | ✓ | ✓ | mosquitto admin: пользователи, ACL, мосты, TLS |
| `controller-backup` | ✓ | ✓ | tar-бэкап (конфиги + Docker volumes) + RESTORE.md |
| `controller-update` | ✓ | ✓ | `apt upgrade`, `wb-release -t`, factoryreset (Сценарий D) |
| `hardware-modules` | ✓ | ✓ | MOD1-4, WBIO, RS-485, Zigbee, CAN, 1-Wire |
| `software-install` | ✓ | ✓ | Docker-by-default, Z2M-нативно, Node-RED, HA, Grafana |
| `zigbee` | ✓ | ✓ | Поиск, спаривание через zigbee2mqtt; wb-mqtt-zigbee/wb-zigbee2mqtt |
| `history` | ✓ | ✓ | wb-mqtt-db: точки + агрегаты + SVG-чарты Vega-Lite |
| `bugreport` | ✓ | ✓ | Сбор данных для поддержки + diag-архив |
| `diagrams` | ✓ | — | Mermaid-диаграммы автоматизации |
| `documentation-search` | ✓ | — | Поиск по wiki/GitHub Wiren Board |

`diagrams` и `documentation-search` не зависят от контроллера — MCP-варианты избыточны. Подключай их из `skills/bash/` независимо от того, какой основной flavor используешь.

## MCP Tools (краткая карта)

43 tool в 11 группах. Полная таблица — в [`mcp-server/README.md`](mcp-server/README.md).

- **Discovery (3):** `wb_discover`, `wb_probe`, `wb_add_controller`
- **SSH+файлы (4):** `wb_ssh_exec`, `wb_ssh_exec_async`, `wb_read_file`, `wb_write_file`
- **Async jobs (3):** `wb_job_status`, `wb_job_tail`, `wb_job_cancel` (через systemd-run + script-file + `StandardOutput=append:`)
- **MQTT (4):** `wb_mqtt_read`, `wb_mqtt_write` (с `retain`/`qos`), `wb_mqtt_list`, `wb_mqtt_rpc`
- **MQTT-устройства (3):** `wb_mqtt_devices`, `wb_mqtt_controls`, **`wb_mqtt_inventory`** (сводно: id+driver+error+controls с распакованным meta и error-флагами по [WB Conventions](https://github.com/wirenboard/conventions))
- **Confed (2):** `wb_confed_load`, `wb_confed_save` (валидация JSON + атомарный рестарт сервиса)
- **wb-rules (5):** `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_disable`, `wb_rules_delete`
- **History (2):** `wb_history`, `wb_history_chart` (Vega-Lite SVG: line/bar/area/heatmap, 1/2/3+ unit-стратегии)
- **Audit/state (3):** `wb_audit`, `wb_state_save`, `wb_state_diff`
- **Modbus/serial (6):** `wb_modbus_template`, `wb_modbus_templates_list`, `wb_modbus_device_info`, `wb_modbus_probe`, `wb_modbus_ports`, **`wb_modbus_scan`** (через `wb-device-manager/bus-scan/Start`, async, extended Fast Modbus), **`wb_modbus_add_devices`** (auto-add найденного в конфиг с `dryRun`)
- **Diagnostics (7):** `wb_metrics`, `wb_logs` (с `since`/`grep`/`grepInvert`), `wb_failed`, `wb_serial_debug`, `wb_systemd_unit`, `wb_network_status`, `wb_cloud_status`

## Архитектурные моменты

- **SSH host-key:** MCP-сервер использует `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null`. Это переживает factory reset / FIT-прошивку без ручного `ssh-keygen -R`. Контроллер в локальной сети — доверенная среда.
- **Async-задачи:** через `systemd-run --collect` + script-file (`/mnt/data/ai/wb-ai-integration/jobs/<id>.sh`) + `StandardOutput=append:`. Никаких трюков с shell-redirect, переживает разрыв SSH, gc по 24-часовому TTL.
- **MQTT-error по WB Conventions:** `wb_mqtt_inventory` парсит `<...>/meta/error` в флаги `{read, write, periodMiss}`. При `read=true` value-топик содержит **last-known-good** значение (см. [WB Conventions](https://github.com/wirenboard/conventions)).
- **Имена с пробелами:** WB-MR6C и подобные имеют контролы `Input 0`, `Input 0 counter` — пробелы являются частью имени. Использован `mosquitto_sub -F '%t\t%p'` (TAB-разделитель), чтобы не резать суффикс при парсинге.

## Требования

- **Хост-машина:** Linux (для bun-MCP-сервера). MacOS — не тестировался, должен работать. Windows — нет.
- **Bun 1.3+** — для MCP-flavor.
- **avahi (`avahi-browse`, mDNS)** — для discovery контроллеров.
- **`mosquitto-clients`** — `mosquitto_sub`/`mosquitto_pub` нужны на хосте, если используешь bash-flavor извне; на контроллерах WB они есть по умолчанию.
- **`sshpass`** — если SSH через пароль (по умолчанию `wirenboard`); если через ключ — не нужен.
- **`jq`** — для bash-скиллов с парсингом JSON.
- **Claude Code CLI** или **opencode**.

## Лицензия

MIT (см. [LICENSE](LICENSE)).

## Связанные проекты

- [`wb-ai-helper-desktop`](https://github.com/wirenboard/wb-ai-helper-desktop) — standalone desktop-приложение Wiren Board для общения с контроллерами через LLM (своя БД, UI, инкапсулирует Anthropic/OpenAI/AITunnel API).
