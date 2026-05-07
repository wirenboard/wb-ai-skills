---
name: zigbee
description: Zigbee-устройства на WB — поиск, спаривание, управление через zigbee2mqtt.
allowed-tools: Bash Read WebFetch
---

# zigbee

Zigbee-устройства на контроллере Wiren Board через zigbee2mqtt.

## Архитектура

**zigbee2mqtt** общается с Zigbee-адаптером через `/dev/ttyMOD<N>` и публикует в `zigbee2mqtt/<friendly_name>`. Запущен может быть **либо нативно** (`systemctl is-active zigbee2mqtt`), **либо в Docker** (`docker ps | grep zigbee`) — оба случая встречаются. Способ установки **не определяется по `systemctl`** — он точно покажет `inactive` для контейнерной инсталляции даже когда мост работает.

WB-конвертеры превращают Z2M-устройства в нативные WB-MQTT (`/devices/...`), чтобы их видели wb-rules и Web UI:

| Конвертер | Топик-префикс | Особенности |
|-----------|---------------|-------------|
| **wb-mqtt-zigbee** (новый) | `/devices/zigbee_*/controls/*` | Двусторонние контролы, поддержка через `/on` |
| **wb-zigbee2mqtt** (старый, `1.x`) | `/devices/0x<ieee>/controls/*` (имя топика = IEEE-адрес целиком) | Readonly мост, управление — через `mosquitto_pub zigbee2mqtt/<friendly>/set` |

Какой стоит — определяй через `dpkg -l | grep -E 'wb-(mqtt-zigbee\|zigbee2mqtt)'` и `mosquitto_sub /devices/+/meta/name -C 50 -W 3` (посмотри, есть ли там `0x...` имена или `zigbee_<id>`).

## Как опознать

Признаки:
- В MQTT есть устройства с именами `0x00158d...`, `0x00124b...`, `0x04cd15...`, `0xd44867...` — это IEEE-адреса (Zigbee).
- В `/devices/...` могут быть оба формата: `/devices/0x<ieee>` (старый конвертер) или `/devices/zigbee_<id>` (новый).
- Топики `zigbee2mqtt/bridge/state`, `zigbee2mqtt/bridge/devices`, `zigbee2mqtt/bridge/info` — публикует сам Z2M независимо от конвертера WB.

## Probe моста

**Истинная проверка живости — `bridge/state`, не `systemctl`:**

```bash
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/state' -C 1 -W 5"
```

Ожидание: `{"state":"online"}` (или просто `online` на старых версиях). Если пусто/таймаут — мост мёртв или нет MQTT-связи.

Только если `bridge/state` пуст, разбирайся **где** именно лежит Z2M:

```bash
ssh root@<HOST> 'systemctl is-active zigbee2mqtt 2>&1; docker ps --format "{{.Names}} {{.Status}}" 2>/dev/null | grep -i zigbee'
```

Один из двух (или оба) ответят. Дальше — `journalctl -u zigbee2mqtt -n 50` или `docker logs --tail 50 zigbee2mqtt`.

## Информация о мосте и устройствах

`bridge/devices` — большой JSON (десятки КБ). Не пытайся `head -c 200` — это даст битый JSON, который не распарсить. Сразу пиши целиком:

```bash
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/devices' -C 1 -W 5" > /tmp/z2m-devices.json
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/info'    -C 1 -W 5" > /tmp/z2m-info.json
```

**Парсинг — через jq** (есть на всех актуальных WB-прошивках):

```bash
# Список устройств: friendly_name | ieee | model | vendor
jq -r '.[] | select(.type != "Coordinator") | [.friendly_name, .ieee_address, .definition.model // "?", .definition.vendor // "?"] | @tsv' /tmp/z2m-devices.json
```

Если `jq` нет (минимальный образ или совсем старый релиз) — `python3 -c '...'` как fallback. Не вкладывай python в один SSH-вызов с f-strings: переход кавычек хрупок. Проще скопировать `.json` локально и распарсить на хосте.

`bridge/info` содержит: `version` (Z2M), `coordinator.type` (адаптер: ZStack3x0, EmberZNet и т.п.), `permit_join` (bool, должно быть `false` в спокойном состоянии), `restart_required`, `config.availability.enabled`.

**`last_seen` per-device** — публикуется в `bridge/devices` **только если** в `configuration.yaml` стоит `availability.enabled: true`. По умолчанию выключено — отсутствие поля **не значит**, что устройство офлайн.

## Текущие значения устройства

```bash
# Текущие значения через Z2M (raw):
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/<friendly_name>' -C 1 -W 5"

# Через WB-конвертер (зависит от того, какой стоит):
# Новый wb-mqtt-zigbee:
ssh root@<HOST> "mosquitto_sub -t '/devices/zigbee_<id>/controls/+' -C 50 -W 3"
# Старый wb-zigbee2mqtt:
ssh root@<HOST> "mosquitto_sub -t '/devices/0x<ieee>/controls/+' -C 50 -W 3"
```

## Управление устройством

**Запись через WB-конвертер (если есть `wb-mqtt-zigbee`):**
```bash
ssh root@<HOST> "mosquitto_pub -t '/devices/zigbee_<id>/controls/<channel>/on' -m '<value>'"
```

**Через Z2M напрямую (всегда работает):**
```bash
ssh root@<HOST> "mosquitto_pub -t 'zigbee2mqtt/<friendly_name>/set' -m '{\"state\":\"ON\"}'"
```

## Спаривание

⚠️ **Это меняет состояние моста.** До спаривания согласовывай с пользователем — после `permit_join: true` любое Zigbee-устройство в радиусе может присоединиться без авторизации.

Включить режим спаривания на 4 минуты:
```bash
ssh root@<HOST> "mosquitto_pub -t 'zigbee2mqtt/bridge/request/permit_join' -m '{\"value\": true, \"time\": 240}'"
```

Зажми кнопку pair на устройстве. После спаривания **обязательно выключи**:
```bash
ssh root@<HOST> "mosquitto_pub -t 'zigbee2mqtt/bridge/request/permit_join' -m '{\"value\": false}'"
```

Проверь, что выключилось:
```bash
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/info' -C 1 -W 5" | jq '.permit_join'
# должно быть false
```

## Грабли

- `systemctl is-active zigbee2mqtt` ≠ probe моста. Если Z2M в Docker, ответ всегда `inactive`. Используй `bridge/state`.
- `mosquitto_sub -t 'zigbee2mqtt/#'` — мегабайты данных (вся история retained). Не делай.
- `head -c 200` для `bridge/devices` — даёт битый JSON, не парсится.
- Отсутствие `last_seen` ≠ устройство офлайн. Проверь `bridge/info → config.availability.enabled`.
- `bridge/request/permit_join` без подтверждения пользователя — деструктивно.
- LQI < 80 + voltage < 2900 мВ — батарейка скоро сдохнет, даже если `battery: 100%` (CR2032 даёт 100% до самого конца, потом резко падает).
- Модули WBE2R-R-ZIGBEE и подобные на странице «Устройства» Web UI не видны — это нормально, они на стороне Z2M.

## Документация

- <https://wiki.wirenboard.com/wiki/Zigbee>
- <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>
- <https://wiki.wirenboard.com/wiki/WBE2R-R-ZIGBEE_v.2_ZigBee_Extension_Module>
