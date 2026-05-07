---
name: zigbee
description: Zigbee-устройства на WB через MCP — поиск, спаривание, управление через zigbee2mqtt.
allowed-tools: Bash Read WebFetch
---

# zigbee (MCP)

Zigbee-устройства на контроллере Wiren Board через zigbee2mqtt. Управление и состояние идут через MQTT — используй `wb_mqtt_*` tools.

## Архитектура

**zigbee2mqtt** общается с Zigbee-адаптером через `/dev/ttyMOD<N>` и публикует в `zigbee2mqtt/<friendly_name>`. Запущен может быть **либо нативно** (через systemd), **либо в Docker** — оба случая встречаются. `wb_failed` для Docker-инсталляции ничего не покажет даже когда мост работает.

WB-конвертеры превращают Z2M-устройства в нативные WB-MQTT (`/devices/...`), чтобы их видели wb-rules и Web UI:

| Конвертер | Топик-префикс | Особенности |
|-----------|---------------|-------------|
| **wb-mqtt-zigbee** (новый) | `/devices/zigbee_*/controls/*` | Двусторонние контролы, поддержка через `/on` |
| **wb-zigbee2mqtt** (старый, `1.x`) | `/devices/0x<ieee>/controls/*` (имя топика = IEEE-адрес целиком) | Readonly мост, управление через `zigbee2mqtt/<friendly>/set` |

Какой стоит — `wb_ssh_exec` `dpkg -l | grep -E "wb-(mqtt-zigbee\|zigbee2mqtt)"` и `wb_mqtt_devices` (посмотри, есть ли там `0x...` или `zigbee_...` имена).

## Как опознать

- IEEE-адреса `0x00158d...`, `0x00124b...`, `0x04cd15...`, `0xd44867...` в `wb_mqtt_devices` — это Zigbee.
- В `/devices/...` могут быть оба формата: `0x<ieee>` (старый конвертер) или `zigbee_<id>` (новый) — НЕ предполагай заранее.
- Топики `zigbee2mqtt/bridge/state`, `bridge/devices`, `bridge/info` — публикует сам Z2M, формат не зависит от конвертера.

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Probe моста (правильный путь) | `wb_mqtt_read topic=zigbee2mqtt/bridge/state` |
| Z2M в Docker / нативно — где живёт | `wb_ssh_exec` `systemctl is-active zigbee2mqtt 2>&1; docker ps --format "{{.Names}}" 2>/dev/null \| grep -i zigbee` |
| Информация о мосте (версия, координатор, permit_join) | `wb_mqtt_read topic=zigbee2mqtt/bridge/info` |
| Спаренные устройства (raw JSON, может быть >20 КБ) | `wb_mqtt_read topic=zigbee2mqtt/bridge/devices` |
| Включить/выключить permit_join (⚠️ деструктивно) | `wb_mqtt_write topic=zigbee2mqtt/bridge/request/permit_join` |
| Чтение состояния устройства (raw Z2M) | `wb_mqtt_read topic=zigbee2mqtt/<friendly_name>` |
| Чтение через WB-конвертер | `wb_mqtt_controls device=zigbee_<id>` или `wb_mqtt_controls device=0x<ieee>` |
| Управление через WB-конвертер | `wb_mqtt_write topic=/devices/zigbee_<id>/controls/<c>/on` |
| Управление через Z2M напрямую | `wb_mqtt_write topic=zigbee2mqtt/<friendly_name>/set value='{"state":"ON"}'` |
| Логи Z2M (нативный) | `wb_logs unit=zigbee2mqtt` |
| Логи Z2M (контейнер) | `wb_ssh_exec` `docker logs --tail 50 zigbee2mqtt` |

## Probe моста — правильный путь

**`wb_failed` не подходит для probe Z2M в Docker.** Используй `wb_mqtt_read zigbee2mqtt/bridge/state` — он работает независимо от способа установки.

```
wb_mqtt_read sn=<SN> topic=zigbee2mqtt/bridge/state
```

Ожидание: `{"state":"online"}` (или `online` в старых версиях). Пусто/таймаут — мост мёртв или нет MQTT-связи.

Если пусто — разбирайся, **где** лежит Z2M:
- `wb_ssh_exec` `systemctl is-active zigbee2mqtt 2>&1` (`active` → нативный) **или**
- `wb_ssh_exec` `docker ps --format "{{.Names}} {{.Status}}" \| grep -i zigbee` (`Up ...` → контейнер).

Логи: `wb_logs unit=zigbee2mqtt` (для нативного) или `wb_ssh_exec` `docker logs --tail 50 zigbee2mqtt` (для контейнера).

## Информация о мосте

```
wb_mqtt_read sn=<SN> topic=zigbee2mqtt/bridge/info
```

Содержит: `version` (Z2M), `coordinator.type` (адаптер: ZStack3x0, EmberZNet и т.п.), `permit_join` (должен быть `false` в спокойном состоянии), `restart_required`, `config.availability.enabled`.

**`last_seen` per-device** в `bridge/devices` публикуется только если в `configuration.yaml` стоит `availability.enabled: true`. По умолчанию выключено — отсутствие поля **не значит**, что устройство офлайн.

## Спаривание

⚠️ **Деструктивно** — после `permit_join: true` любое Zigbee-устройство в радиусе может присоединиться. Согласуй с пользователем.

```
wb_mqtt_write sn=<SN> topic=zigbee2mqtt/bridge/request/permit_join value='{"value": true, "time": 240}'
```

После спаривания обязательно выключи:

```
wb_mqtt_write sn=<SN> topic=zigbee2mqtt/bridge/request/permit_join value='{"value": false}'
```

Подтверди:
```
wb_mqtt_read sn=<SN> topic=zigbee2mqtt/bridge/info
# в ответе permit_join должен быть false
```

После успешного спаривания — `wb_mqtt_devices` покажет новый IEEE/friendly_name.

## Грабли

- `wb_failed` ≠ probe моста для Docker-Z2M.
- `wb_mqtt_list prefix=zigbee2mqtt/` без ограничений может вернуть всю Z2M-историю (десятки топиков). Лучше точечно через `wb_mqtt_read`.
- `bridge/devices` — большой JSON. Усечение (`head -c 200` и т.п.) не имеет смысла, парсить только целиком.
- Отсутствие `last_seen` ≠ устройство офлайн. Проверь `bridge/info → config.availability.enabled`.
- LQI < 80 + voltage < 2900 мВ — батарейка скоро сдохнет, даже если `battery: 100%` (CR2032 даёт 100% до самого конца).
- Модуль WBE2R-R-ZIGBEE не виден на странице «Устройства» в Web UI — это нормально, он на стороне Z2M.

**Установка Z2M** — `/software-install` (нативно из WB-репо, **не** Docker — привязка к адаптеру).

## Документация

- <https://wiki.wirenboard.com/wiki/Zigbee>
- <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>
- <https://wiki.wirenboard.com/wiki/WBE2R-R-ZIGBEE_v.2_ZigBee_Extension_Module>
