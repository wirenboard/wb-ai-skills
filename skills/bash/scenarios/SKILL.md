---
name: scenarios
description: Сценарии Web UI Wiren Board (`wb-scenarios`) — декларативные правила без кода. devicesControl, lightControl, thermostat, schedule. Конфиг /etc/wb-scenarios.conf.
allowed-tools: Bash Read Write WebFetch
---

# scenarios

`wb-scenarios` — отдельный движок поверх `wb-rules`, который из декларативного JSON в `/etc/wb-scenarios.conf` генерирует JS-правила. Это «no-code» уровень для типовых задач: управление группами устройств, освещение по датчику движения, термостат, расписание.

Подгружай при: «сделай сценарий», «настрой термостат», «свет по датчику движения», «по расписанию выключай», `wb-scenarios.conf`, «сценарии в Web UI».

**Не путай с `/wb-rules`** (полноценный JS, ES5, defineRule). Сценарии — упрощённая надстройка для типового. Если задача нестандартная или нужны вычисления — иди в wb-rules.

## Архитектура

```
/etc/wb-scenarios.conf   (через confed, JSON)
       │
       ▼
wb-scenarios-reloader.service
       │ (генерирует .js под капотом)
       ▼
/etc/wb-rules/<генерированные правила>
       │
       ▼
wb-rules engine
```

Сервис: `wb-scenarios-reloader` (НЕ `wb-scenarios.service` — её нет).

Schema: `/usr/share/wb-mqtt-confed/schemas/wb-scenarios.schema.json` — описывает 4 типа сценариев и UI.

## Четыре типа сценариев

### 1. `devicesControl` — групповое управление

«Когда контрол A меняется → выставить контролы B и C». Базовая автоматизация.

```json
{
  "scenarioType": "devicesControl",
  "name": "Свет в коридоре",
  "id_prefix": "corridor_light",
  "enable": true,
  "inControls": [
    {"deviceId": "wb-mwac_25", "controlId": "Input 1"}
  ],
  "outControls": [
    {"deviceId": "wb-mr6c_2", "controlId": "K1", "value": true}
  ]
}
```

`inControls` — триггеры (изменение значения), `outControls` — что выставить с каким значением.

### 2. `lightControl` — освещение

Включение по датчику движения с таймером выключения, ночной режим, диммирование.

```json
{
  "scenarioType": "lightControl",
  "name": "Свет в туалете",
  "id_prefix": "wc_light",
  "enable": true,
  "motionSensor": {"deviceId": "wb-msw-v4_20", "controlId": "Motion"},
  "lightOutput": {"deviceId": "wb-mr6c_2", "controlId": "K2"},
  "delayOff": 60,
  "ambientLightSensor": {"deviceId": "wb-msw-v4_20", "controlId": "Illuminance"},
  "darkThreshold": 100
}
```

### 3. `thermostat` — термостат

Включение нагревателя по разнице setpoint - current с гистерезисом.

```json
{
  "scenarioType": "thermostat",
  "name": "Гостиная",
  "id_prefix": "living_room",
  "enable": true,
  "temperatureSensor": {"deviceId": "wb-msw-v4_20", "controlId": "Temperature"},
  "heaterOutput": {"deviceId": "wb-mr6c_2", "controlId": "K3"},
  "setpoint": 22.0,
  "hysteresis": 0.5
}
```

### 4. `schedule` — расписание

«Каждый день в HH:MM сделать X». Под капотом — wb-rules cron.

```json
{
  "scenarioType": "schedule",
  "name": "Полив",
  "id_prefix": "watering",
  "enable": true,
  "schedule": {"hour": 6, "minute": 30, "days": [1,2,3,4,5,6,7]},
  "actions": [
    {"deviceId": "wb-mr6c_2", "controlId": "K4", "value": true},
    {"deviceId": "wb-mr6c_2", "controlId": "K4", "value": false, "delay": 1800}
  ]
}
```

`days` — `[1..7]` (1=пн … 7=вс). `delay` — задержка после предыдущего action (сек).

## Базовые команды

```bash
ssh root@<HOST> 'cat /etc/wb-scenarios.conf'                                # текущий
ssh root@<HOST> 'systemctl status wb-scenarios-reloader --no-pager'         # статус
ssh root@<HOST> 'journalctl -u wb-scenarios-reloader -n 30 --no-pager'      # логи
ssh root@<HOST> 'ls /etc/wb-rules/wb-scenario-*.js 2>/dev/null'             # сгенерированные .js
```

После правки конфига `wb-scenarios-reloader` сам пересоздаёт правила и перезапускает `wb-rules`.

## Правка через confed (рекомендованный путь)

```bash
ssh root@<HOST> 'CID=ai-$(date +%s); mosquitto_sub -t "/rpc/v1/confed/Editor/Save/$CID/reply" -C 1 -W 10 & sleep 0.2; \
  PAYLOAD=$(jq -nc --rawfile c /tmp/scenarios.conf.new "{id:1,params:{path:\"/etc/wb-scenarios.conf\",content:(\$c|fromjson)}}"); \
  mosquitto_pub -t "/rpc/v1/confed/Editor/Save/$CID" -m "$PAYLOAD"; wait'
```

`content` — **JSON-объект**, не строка (см. `/wb-mqtt-serial`, тот же формат).

## Прямая правка файла

Можно `wb_write_file` или `cat >`, но **обязательно** перезагрузить генератор:

```bash
ssh root@<HOST> 'systemctl restart wb-scenarios-reloader'
```

Через confed — рестарт автоматический, через прямую правку — руками.

## Когда сценария мало — ходить в wb-rules

- Условие зависит от нескольких контролов одновременно с логикой.
- Нужна вычислимая величина (среднее, гистерезис не симметричный, PID).
- Нужно состояние (счётчики, триггер «N раз подряд»).
- Нужны таймеры, отличные от schedule (interval, экспоненциальная задержка).
- Виртуальные устройства.

Сценарии хороши для «нажал кнопку → включил реле» и «по таймеру включил/выключил». Дальше — wb-rules.

## Грабли

- **`wb-scenarios.service` не существует** — сервис называется `wb-scenarios-reloader`.
- **id_prefix дубликат** — два сценария с одним `id_prefix` сгенерируют пересекающиеся имена правил, конфликт.
- **Прямая правка `/etc/wb-rules/wb-scenario-*.js`** — затрётся при следующем reload. Только через `wb-scenarios.conf`.
- **Кириллица в `id_prefix`** — schema запрещает (regex `^[0-9a-zA-Z_]+$`). В `name` — можно.
- **Сценарий не появился в Web UI** — проверь `journalctl -u wb-scenarios-reloader` на ошибки парсинга. Конфиг битый — Web UI не покажет ничего.
- **Сценарий и аналогичное правило wb-rules** — конфликтуют (оба пишут в один контрол). Не дублируй.
- **`schedule` без часового пояса** — использует системный (`timedatectl`). После апгрейда timezone сценарии могут «съехать».

## Документация

- WB wiki — сценарии: <https://wirenboard.com/wiki/Wb-scenarios>
- Schema: `/usr/share/wb-mqtt-confed/schemas/wb-scenarios.schema.json` на контроллере.
