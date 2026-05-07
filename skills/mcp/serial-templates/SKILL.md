---
name: serial-templates
description: Создание кастомных Modbus-шаблонов для wb-mqtt-serial через MCP. /etc/wb-mqtt-serial.conf.d/templates/. Структура файла, регистры, форматы, parameters, groups.
allowed-tools: Bash Read Write WebFetch
---

# serial-templates (MCP)

Создание собственных шаблонов Modbus-устройств через `wb_*` tools. Когда устройства нет среди 250+ встроенных.

Подгружай при: «нет шаблона для устройства», «добавь Modbus-устройство <стороннего>», «создай шаблон», «как добавить кастомные регистры».

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Найти похожий встроенный шаблон как стартовый | `wb_modbus_templates_list filter="<тип>"` |
| Прочитать существующий шаблон | `wb_modbus_template device_type=<тип> view=full` |
| Записать кастомный шаблон | `wb_write_file path=/etc/wb-mqtt-serial.conf.d/templates/<имя>.json` |
| Применить (рестарт драйвера) | `wb_systemd_unit unit=wb-mqtt-serial action=restart` |
| Проверить парсинг шаблона | `wb_logs unit=wb-mqtt-serial since="1m ago" grep="(?i)template"` |
| Проверить публикацию канала | `wb_mqtt_read topic=/devices/<device.id>_<slave_id>/controls/<channel>` |
| Прямое чтение регистра для калибровки scale/format | `wb_ssh_exec` `modbus_client_rpc -m rtu -a <slave> -t 4 -r <addr> -c <count> -b <baud> -s 2 -p N <port>` |
| Backup кастомных шаблонов | `/controller-backup` (`/etc/wb-mqtt-serial.conf.d/` уже в core-tar) |

## Где живут шаблоны

| Каталог | Что | Можно править? |
|---------|-----|----------------|
| `/usr/share/wb-mqtt-serial/templates/` | Пакетные WB и Onokom | НЕТ — затрутся apt'ом |
| `/etc/wb-mqtt-serial.conf.d/templates/<любое>.json` | Кастомные | Да, переживают апгрейд |

Кастомный с тем же `device_type` как пакетный — **переопределяет**.

## Минимальный шаблон

```json
{
  "title": "ACME EM-100",
  "device_type": "ACME-EM100",
  "group": "g_energy_meters",
  "device": {
    "name": "ACME EM-100",
    "id": "acme-em100",
    "channels": [
      {"name":"Voltage","reg_type":"input","address":0,"format":"u32","scale":0.1,"type":"voltage","units":"V"},
      {"name":"Current","reg_type":"input","address":2,"format":"u32","scale":0.001,"type":"current","units":"A"}
    ]
  }
}
```

## Workflow

1. **Документация устройства** — `WebFetch` мануал производителя. Без таблицы регистров (адрес/тип/scale) шаблон не делай.
2. **Стартовый похожий шаблон** — `wb_modbus_templates_list filter="<категория>"`, потом `wb_modbus_template device_type=<похожий> view=full`. Скопируй структуру.
3. **Запиши кастомный** — `wb_write_file path=/etc/wb-mqtt-serial.conf.d/templates/<имя>.json` с одним каналом для теста.
4. **Рестарт драйвера** — `wb_systemd_unit unit=wb-mqtt-serial action=restart`.
5. **Шаблон в списке?** — `wb_modbus_templates_list filter="<твой device_type>"` должен показать.
6. **Добавь устройство в конфиг** — `wb_confed_load /etc/wb-mqtt-serial.conf` → дополни `ports[*].devices` записью с твоим `device_type` → `wb_confed_save`.
7. **Проверь публикацию** — `wb_mqtt_read topic=/devices/<device.id>_<slave_id>/controls/<channel>`. Значение правдоподобное?
8. **Калибровка `format`/`scale`/`word_order`** — `wb_ssh_exec` `modbus_client_rpc` для прямого raw, сравни с тем что публикует драйвер.
9. **Расширь до всех каналов** — пачками по 5-10, проверка после каждой.
10. **Параметры и группы** — после телеметрии.

## Поля channel (ключевые)

| Поле | Назначение |
|------|-----------|
| `reg_type` | `coil` (FC1), `discrete` (FC2), `holding` (FC3), `input` (FC4) |
| `address` | Адрес регистра (0-based; некоторые мануалы дают 1-based — проверь) |
| `format` | `u8/s8/u16/s16/u32/s32/float/string/varstring/bcd16/bcd32` |
| `scale` | `value = raw * scale` |
| `word_order` | `big_endian` (default) или `little_endian` для u32/s32/float |
| `error_value` | Raw == этому → MQTT `error` |
| `condition` | Виден только если выражение по `parameters` истина |
| `enabled` | `false` — есть в шаблоне, по умолчанию выключен |
| `readonly` | `true` — даже у `holding`/`coil` только чтение |

## Структура `parameters` и `groups` — см. bash-двойник.

## Грабли

- **Шаблон в `/usr/share/wb-mqtt-serial/templates/`** — затрётся apt'ом. Только `/etc/wb-mqtt-serial.conf.d/templates/`.
- **Endianness** — для u32/s32/float `word_order: little_endian` если значение прыгает 65535-кратно.
- **Scale в обратную сторону** — `raw / 10` vs `raw * 0.1`. Тест на одном канале.
- **Дубликат `device_type`** — переопределяет пакетный молча. Используй префикс (`ACME-`, `MY-`).
- **Кириллица в `device.id`** — нельзя, идёт в имя топика. Только `[a-z0-9-]`.
- **Адрес 0-based vs 1-based** — стандарт Modbus 0-based, мануалы часто 1-based.
- **Без `error_value`** — FFFF опубликуется как 65535 валидное значение.

## Связанные скиллы

- `/wb-mqtt-serial` — конфиг драйвера (добавление устройства с твоим device_type).
- `/troubleshooting-serial` — проблемы CRC/таймаутов при разработке.
- `/controller-backup` — `/etc/wb-mqtt-serial.conf.d/` в архиве.

Подробности (полный список полей, endianness, примеры формата) — bash-двойник `/serial-templates`.

## Документация

- Формат шаблона: <https://github.com/wirenboard/wb-mqtt-serial/blob/master/docs/template.md>
- Modbus FC: <https://modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf>
- Примеры: 250+ шаблонов на контроллере, см. `wb_modbus_templates_list`.
