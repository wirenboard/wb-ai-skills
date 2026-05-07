# WB MCP Server

MCP-сервер для управления контроллерами [Wiren Board](https://wirenboard.com) через [Claude Code](https://claude.ai/code).

43 инструмента: SSH, MQTT (включая `wb_mqtt_inventory`), mDNS discovery, wb-rules (включая `wb_rules_disable`), Modbus (включая `wb_modbus_templates_list` и `wb_modbus_add_devices` для авто-добавления найденного сканером), история + SVG-чарты (`wb_history_chart`), аудит, фоновые задачи (через systemd-run + script-file), systemd (`wb_systemd_unit`), сеть (`wb_network_status`), облако (`wb_cloud_status`).

## Установка

```bash
cd mcp-server
bun install
```

## Подключение к Claude Code

Скопируй `.mcp.json.example` → `.mcp.json` в проект или `~/.claude/`:

```json
{
  "mcpServers": {
    "wiren-board": {
      "command": "bun",
      "args": ["run", "/path/to/mcp-server/src/index.ts"],
      "env": {
        "WB_SSH_USER": "root",
        "WB_SSH_PASSWORD": "wirenboard"
      }
    }
  }
}
```

Или через CLI:
```bash
claude mcp add wiren-board -- bun run /path/to/mcp-server/src/index.ts
```

## Инструменты

### Discovery (3)
| Tool | Описание |
|------|----------|
| `wb_discover` | Контроллеры в сети (mDNS + ручные) |
| `wb_probe` | Доступность + системная информация |
| `wb_add_controller` | Добавить вручную по hostname/IP |

### SSH & Files (4)
| Tool | Описание |
|------|----------|
| `wb_ssh_exec` | Команда (синхронно, до 2 мин) |
| `wb_ssh_exec_async` | Фоновая задача через systemd-run |
| `wb_read_file` | Прочитать файл (до 64 КБ) |
| `wb_write_file` | Записать файл (SFTP) |

### Background Jobs (3)
| Tool | Описание |
|------|----------|
| `wb_job_status` | Статус (running/exited) |
| `wb_job_tail` | Лог (инкрементально) |
| `wb_job_cancel` | Отменить |

### MQTT (4)
| Tool | Описание |
|------|----------|
| `wb_mqtt_read` | Retained-топик (любой, не только WB) |
| `wb_mqtt_write` | Записать в топик (с опц. `retain`/`qos` — для произвольных не-WB топиков и интеграций) |
| `wb_mqtt_list` | Топики по префиксу (любой `+`/`#` wildcard) |
| `wb_mqtt_rpc` | RPC-вызов (wb-mqtt-serial, confed, wbrules, db_logger) |

### MQTT Devices (3)
| Tool | Описание |
|------|----------|
| `wb_mqtt_devices` | Только id → name |
| `wb_mqtt_controls` | Raw топики одного устройства |
| `wb_mqtt_inventory` | **Сводно**: устройства + driver + error + контролы (value/type/units/readonly/order/error). Один вызов вместо N+1. Фильтр по `device` (substring). |

### Confed Configuration (2)
| Tool | Описание |
|------|----------|
| `wb_confed_load` | Загрузить конфиг (/etc/wb-mqtt-serial.conf, /etc/wb-hardware.conf) |
| `wb_confed_save` | Сохранить (валидация + рестарт сервиса) |

### wb-rules (5)
| Tool | Описание |
|------|----------|
| `wb_rules_list` | Список правил (.js, enabled/disabled) |
| `wb_rules_load` | Прочитать правило |
| `wb_rules_save` | Сохранить (валидация JS + reload) |
| `wb_rules_delete` | Удалить целиком (`Editor/Remove`) |
| `wb_rules_disable` | Выключить файл (`<name>.js` → `<name>.js.disabled`) без удаления |

### History (2)
| Tool | Описание |
|------|----------|
| `wb_history` | Данные из wb-mqtt-db (точки + min/max/avg) |
| `wb_history_chart` | SVG-чарт через Vega-Lite. Типы: line/bar/area/point/histogram/heatmap/boxplot. 1 unit → одна шкала, 2 → двойная Y-ось, 3+ → нормализация в [0;1] |

### Audit & State (3)
| Tool | Описание |
|------|----------|
| `wb_audit` | Аудит: пакеты, сервисы, кастомные файлы |
| `wb_state_save` | Слепок состояния системы |
| `wb_state_diff` | Сравнение со слепком |

### Modbus / wb-mqtt-serial (6)
| Tool | Описание |
|------|----------|
| `wb_modbus_templates_list` | Список доступных шаблонов: type, mqtt-id, name, deprecated, group. RPC `wb-mqtt-serial/config/Load.types` |
| `wb_modbus_template` | Содержимое шаблона (все каналы, parameters, groups, translations). По device_type ищет mqtt-id через RPC и читает `/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json` |
| `wb_modbus_device_info` | Текущие параметры прошивки (fw, model, parameters) — НЕ список каналов (для каналов: `wb_modbus_template`) |
| `wb_modbus_probe` | Пинг устройства на шине |
| `wb_modbus_ports` | Параметры RS-485 портов |
| `wb_modbus_scan` | Полный scan шины (mode=all). RPC требует все serial-параметры — defaults 9600/8/N/2 |

### Diagnostics (7)
| Tool | Описание |
|------|----------|
| `wb_metrics` | Нагрузка, память, диск |
| `wb_logs` | Логи сервиса (journalctl) с `since`/`until`/`grep`/`grepInvert` |
| `wb_failed` | Упавшие systemd-сервисы |
| `wb_serial_debug` | Сбор raw RS-485 пакетов |
| `wb_systemd_unit` | Status (parsed), start/stop/restart/enable/disable/mask/cat/list-deps |
| `wb_network_status` | Интерфейсы + NM-соединения + default route + опц. ping |
| `wb_cloud_status` | wb-cloud-agent: сервис, MQTT-статус, сертификат, providers |

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `WB_SSH_USER` | `root` | SSH-логин |
| `WB_SSH_PASSWORD` | `wirenboard` | SSH-пароль |
| `WB_SSH_KEY` | — | Путь к приватному ключу |
| `WB_DISCOVERY_INTERVAL` | `15000` | Интервал mDNS-скана (мс) |

## Требования

- [Bun](https://bun.sh) 1.3+
- Локальная сеть с контроллерами Wiren Board
- SSH-доступ к контроллерам
