---
name: wb-mqtt-serial
description: "Драйвер Modbus/RS-485 на контроллере Wiren Board через MCP. Конфиг /etc/wb-mqtt-serial.conf, шаблоны, специализированные wb_modbus_* / wb_confed_* tools. Включение/отключение каналов, добавление устройств, сканирование шины, правка конфигурации wb-mqtt-serial."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-mqtt-serial (MCP)

Драйвер Modbus/RS-485. Конфиг `/etc/wb-mqtt-serial.conf`, шаблоны `/usr/share/wb-mqtt-serial/templates/` (пакетные, не трогай) и `/etc/wb-mqtt-serial.conf.d/templates/` (свои). Работай через MCP-tools `wb_modbus_*` и `wb_confed_*` — они инкапсулируют MQTT RPC и confed-валидацию (битый JSON в `.conf` не запишется). `wb_write_file` в `.conf` — только осознанно и с бэкапом.

Подгружай на: «канал не публикуется», «не вижу устройство на шине», «опрос замер», «включи канал X», «просканируй шину», «slave_id / холдинг / coil / input регистр», включение/отключение каналов, добавление/удаление/правка устройств в конфиге wb-mqtt-serial, «добавь modbus-устройство», «удали устройство», «очисти список устройств», «измени конфиг serial», «wb-mqtt-serial.conf», правка ports/devices в конфиге.

**Граница скиллов:** проблема сигнала/CRC/таймаутов — `/troubleshooting-serial`. Создание шаблона устройства, которого нет во встроенных, — отдельный скилл (тут ты этим не занимаешься).

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Список доступных шаблонов (type, mqtt-id, name, deprecated) | `wb_modbus_templates_list` |
| Содержимое шаблона устройства (все каналы, parameters, groups) | `wb_modbus_template` |
| Текущие параметры прошивки устройства (fw, model, parameters) | `wb_modbus_device_info` |
| Жив ли slave_id N на порту X | `wb_modbus_probe` |
| Параметры RS-485 портов | `wb_modbus_ports` |
| Что подключено на шине (Fast Modbus, WB+Onokom + standard для сторонних) | `wb_modbus_scan` (через wb-device-manager, async) |
| Авто-добавить найденное сканером в конфиг | `wb_modbus_add_devices` (с `dryRun=true` для предпросмотра; tool сам подгружает default-значения параметров из шаблона — без них schema-валидация драйвера упадёт на required-параметрах) |
| Прочитать `/etc/wb-mqtt-serial.conf` | `wb_confed_load` |
| Сохранить конфиг (валидация + рестарт сервиса) | `wb_confed_save` |
| Текущее значение канала из MQTT | `wb_mqtt_read` |
| Список устройств / контролов | `wb_mqtt_devices`, `wb_mqtt_controls` |
| Записать кастомный шаблон в `/etc/wb-mqtt-serial.conf.d/templates/` | `wb_write_file` |
| Редкий RPC-метод, не закрытый специализированными tools | `wb_mqtt_rpc` |

## Принципы

- **«Канала нет в MQTT» ≠ «не поддерживается».** Многие каналы шаблонов идут с `"enabled": false` (Uptime, Counter, Total, Serial). Сначала `wb_modbus_template`, потом выводы.
- **Шаблон ищи на контроллере, не на GitHub.** На железке — актуальный под прошивку. `WebFetch` шаблонов почти всегда зря.
- **Кастомный шаблон — последнее средство.** Сначала проверь встроенный.
- **Скан шины медленный.** `wb_modbus_scan` идёт 5-30 сек — у tool правильный таймаут внутри.
- **`wb_confed_save` атомарен.** Битый JSON не пишется, опрос шины жив.

## Сценарий «включи канал X на устройстве Y»

1. `wb_mqtt_devices` (или `wb_mqtt_list prefix=/devices/+/meta/name`) — найди `device_id` (например `wb-mr6c_2`).
2. `wb_confed_load path=/etc/wb-mqtt-serial.conf` — найди устройство в `ports[*].devices[*]`, узнай `device_type` (например `WB-MR6C`).
3. `wb_modbus_template device_type=<тип>` — все каналы шаблона и их `enabled`. (Tool принимает `device_type` или `mqtt-id`, регистронезависимо.)
4. Правь JSON из шага 2 — добавь/обнови запись канала, выстави `"enabled": true`.
5. Покажи пользователю diff, предупреди про рестарт wb-mqtt-serial (опрос замрёт ~5-10 сек).
6. `wb_confed_save` с полным новым JSON.
7. Через 10-20 сек: `wb_mqtt_read` `/devices/<device_id>/controls/<channel>` (timeout 20 сек, чтобы дождаться публикации).

## Сценарий «что подключено на шине»

1. Порты: `wb_modbus_ports` или из `wb_confed_load`.
2. `wb_modbus_scan` на каждом порту с правильными baud/parity/stop. Показывает, что видит драйвер. **Находит только WB и Onokom (Fast Modbus).** Стороннее — не увидит.
3. Сравни с `wb_confed_load` — что уже описано, что добавить.

> `wb_modbus_scan` (этот скилл) — управленческий инструмент драйвера. `wb-device-manager` (скилл `troubleshooting-serial`) — диагностический инструмент. Разные службы, разные цели — не путай.

## Параметры tools

- **`wb_modbus_template`** — `{device_type}` (или `mqtt-id`, регистронезависимо). Возвращает содержимое шаблона из `/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json`. Список доступных типов — `wb_modbus_templates_list filter="<подстрока>"`.
- **`wb_modbus_device_info`** — параметры прошивки конкретного устройства (`fw`, `model`, `parameters`). НЕ возвращает каналы — для каналов используй `wb_modbus_template`. Принимает либо `{device_id: "wb-mr6c_138"}`, либо физический адрес `{path: "/dev/ttyRS485-1", baud_rate: 9600, parity: "N", data_bits: 8, stop_bits: 2, slave_id: 138, device_type: "WB-MR6C"}`.
- **`wb_modbus_probe`** — `{path, slave_id, baud_rate?}` — пинг устройства на шине. Defaults: 9600/8/N/2.
- **`wb_modbus_scan`** — `{port?, baud_rate?, data_bits?, parity?, stop_bits?, mode?}` — без `port` сканирует все порты. Defaults: 9600/8/N/2, mode=all.

## Управление значениями (device/Load, device/Set через wb_mqtt_rpc)

Live-значения каналов, минуя MQTT-публикацию, — `wb_mqtt_rpc service=wb-mqtt-serial method=device/Load params={device_id: "..."}`.

Запись регистров (`device/Set`) — **только по явной просьбе пользователя**: `wb_mqtt_rpc service=wb-mqtt-serial method=device/Set params={device_id, values: {channel_name: value}}`. Эта операция деструктивна для опроса шины на момент записи.

## Прямая правка файла — бэкап обязателен

Если по какой-то причине без `wb_confed_save` (через `wb_write_file`) — сначала бэкап, потом рестарт:

```
wb_ssh_exec sn=<SN> cmd='cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)'
wb_write_file sn=<SN> path=/etc/wb-mqtt-serial.conf content=<JSON>
wb_ssh_exec sn=<SN> cmd='systemctl restart wb-mqtt-serial'
```

Этот путь оправдан только когда `wb_confed_save` не годится (например, нужно записать частично невалидный JSON для эксперимента) — в норме всегда `wb_confed_save`.

## Грабли

- «Канал не поддерживается» по `wb_mqtt_devices`/`wb_mqtt_controls` без `wb_modbus_template` — см. выше, `enabled:false` не публикуется.
- `WebFetch` шаблона с GitHub вместо `wb_modbus_template` — на железе актуальнее.
- Кастомный шаблон до проверки встроенного.
- Прямой `wb_write_file` в `.conf` без валидации — битый JSON положит опрос шины. Используй `wb_confed_save`.
- Правка пакетных шаблонов в `/usr/share/...` — перезапишутся апдейтом. Кастом — только в `/etc/wb-mqtt-serial.conf.d/templates/`.

## Документация

- Wiki: <https://wirenboard.com/wiki/wb-mqtt-serial>
- Исходники + шаблоны: <https://github.com/wirenboard/wb-mqtt-serial>
- Страницы модулей: `https://wirenboard.com/wiki/<Модель>` (WB-MR6C, WB-MSW_v.4 и т.п.)
