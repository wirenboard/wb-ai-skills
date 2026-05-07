---
name: scenarios
description: Сценарии Web UI Wiren Board (`wb-scenarios`) через MCP — devicesControl, lightControl, thermostat, schedule. /etc/wb-scenarios.conf через confed.
allowed-tools: Bash Read Write WebFetch
---

# scenarios (MCP)

Декларативные сценарии Web UI (`wb-scenarios`) через `wb_confed_*`. 4 типа: `devicesControl`, `lightControl`, `thermostat`, `schedule`. Под капотом превращаются в wb-rules JS.

Подгружай при: «сделай сценарий», «настрой термостат», «свет по датчику движения», «по расписанию», `wb-scenarios.conf`, «сценарии в Web UI».

**Не путай с `/wb-rules`** (полноценный JS). Сценарии — упрощённая надстройка для типового.

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Текущий конфиг сценариев | `wb_confed_load path=/etc/wb-scenarios.conf` |
| Записать новый конфиг (валидация + reload) | `wb_confed_save path=/etc/wb-scenarios.conf content=<JSON-объект>` |
| Статус генератора | `wb_systemd_unit unit=wb-scenarios-reloader` |
| Логи генератора | `wb_logs unit=wb-scenarios-reloader since="10m ago"` |
| Сгенерированные .js под капотом | `wb_ssh_exec` `ls /etc/wb-rules/wb-scenario-*.js` |

## Четыре типа сценариев

### `devicesControl` — групповое управление

«Контрол A изменился → выставить контролы B и C».

```json
{"scenarioType":"devicesControl","name":"...","id_prefix":"...","enable":true,
 "inControls":[{"deviceId":"wb-mwac_25","controlId":"Input 1"}],
 "outControls":[{"deviceId":"wb-mr6c_2","controlId":"K1","value":true}]}
```

### `lightControl` — освещение

Датчик движения + выход + delayOff. Опционально: датчик освещённости + порог.

```json
{"scenarioType":"lightControl","name":"...","id_prefix":"...","enable":true,
 "motionSensor":{"deviceId":"wb-msw-v4_20","controlId":"Motion"},
 "lightOutput":{"deviceId":"wb-mr6c_2","controlId":"K2"},
 "delayOff":60,
 "ambientLightSensor":{"deviceId":"wb-msw-v4_20","controlId":"Illuminance"},
 "darkThreshold":100}
```

### `thermostat` — термостат

Setpoint + гистерезис + датчик + выход.

```json
{"scenarioType":"thermostat","name":"...","id_prefix":"...","enable":true,
 "temperatureSensor":{"deviceId":"wb-msw-v4_20","controlId":"Temperature"},
 "heaterOutput":{"deviceId":"wb-mr6c_2","controlId":"K3"},
 "setpoint":22.0,"hysteresis":0.5}
```

### `schedule` — расписание

«В HH:MM по дням недели — сделать действия».

```json
{"scenarioType":"schedule","name":"...","id_prefix":"...","enable":true,
 "schedule":{"hour":6,"minute":30,"days":[1,2,3,4,5,6,7]},
 "actions":[
   {"deviceId":"wb-mr6c_2","controlId":"K4","value":true},
   {"deviceId":"wb-mr6c_2","controlId":"K4","value":false,"delay":1800}
 ]}
```

`days`: `[1..7]` (1=пн). `delay`: после предыдущего action (сек).

## Сценарий: добавить новый

1. `wb_confed_load path=/etc/wb-scenarios.conf` — текущий объект.
2. Добавь объект в массив `scenarios`.
3. `wb_confed_save path=/etc/wb-scenarios.conf content=<полный объект>`.
4. `wb_systemd_unit unit=wb-scenarios-reloader` — статус (`active`).
5. `wb_logs unit=wb-scenarios-reloader since="1m ago"` — без ошибок?
6. Проверка работы — поменяй `inControls` через `wb_mqtt_write` или дождись расписания.

## Когда сценария мало — `/wb-rules`

- Условие на нескольких контролах одновременно с логикой.
- Вычислимая величина (среднее, асимметричный гистерезис, PID).
- Состояние (счётчики, «N раз подряд»).
- Кастомные таймеры (interval, экспоненциальная задержка).
- Виртуальные устройства.

## Грабли

- **`wb-scenarios.service` не существует** — `wb-scenarios-reloader`.
- **`id_prefix` дубликат** — пересечение имён сгенерированных правил.
- **Прямая правка `/etc/wb-rules/wb-scenario-*.js`** — затрётся при reload.
- **Кириллица в `id_prefix`** — schema запрещает.
- **Конфликт сценария и wb-rules** — оба пишут в один контрол.
- **`schedule` использует системный timezone** — `timedatectl` должен быть правильный.

## Связанные скиллы

- `/wb-rules` — когда сценарий не покрывает.
- `/wb-mqtt-serial` — добавление новых устройств для inControls/outControls.

Подробности (формат, schema-ограничения) — bash-двойник `/scenarios`.

## Документация

- WB wiki: <https://wirenboard.com/wiki/Wb-scenarios>
