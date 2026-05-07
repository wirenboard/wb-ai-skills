---
name: serial-templates
description: Создание кастомных Modbus-шаблонов для wb-mqtt-serial. Когда устройства нет среди встроенных шаблонов. /etc/wb-mqtt-serial.conf.d/templates/. Структура файла, регистры, форматы, parameters, groups.
allowed-tools: Bash Read Write WebFetch
---

# serial-templates

Создание собственных шаблонов Modbus-устройств для `wb-mqtt-serial`. Применяется когда производитель не WB/Onokom (нет встроенного шаблона) или когда нужно добавить кастомные регистры в существующий.

Подгружай при: «нет шаблона для устройства», «добавь Modbus-устройство <стороннего>», «создай шаблон», «как добавить кастомные регистры», «шаблон для счётчика энергии», «термодатчик через Modbus».

## Где живут шаблоны

| Каталог | Что | Можно править? |
|---------|-----|----------------|
| `/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json` | Пакетные шаблоны WB и Onokom | НЕТ — затрутся `apt upgrade` |
| `/etc/wb-mqtt-serial.conf.d/templates/<любое-имя>.json` | Кастомные шаблоны | Да, переживают апгрейд |
| `/etc/wb-mqtt-serial.conf.d/confs/*.conf` | Кастомные части основного конфига | Реже используется |

`wb-mqtt-serial` сканирует обе директории при старте. Кастомный шаблон с тем же `device_type` как пакетный — **переопределит** пакетный (полезно для патчей; рискованно, потому что забудешь).

## Минимальная структура шаблона

```json
{
  "title": "ACME EM-100 (1-phase energy meter)",
  "device_type": "ACME-EM100",
  "group": "g_energy_meters",
  "device": {
    "name": "ACME EM-100",
    "id": "acme-em100",
    "channels": [
      {
        "name": "Voltage",
        "reg_type": "input",
        "address": 0,
        "format": "u16",
        "scale": 0.1,
        "type": "voltage",
        "units": "V"
      },
      {
        "name": "Current",
        "reg_type": "input",
        "address": 2,
        "format": "u32",
        "scale": 0.001,
        "type": "current",
        "units": "A"
      }
    ]
  }
}
```

`device_type` — то, что попадает в `/etc/wb-mqtt-serial.conf` (`ports[*].devices[*].device_type`).
`device.id` — префикс MQTT-топика (`wb-mqtt-serial` создаст `/devices/<id>_<slave_id>/...`).

## Поля channel (полный набор)

| Поле | Назначение |
|------|-----------|
| `name` | Имя контрола в MQTT (с пробелами OK: `Input 0`, `Input 0 counter`) |
| `reg_type` | `coil` (FC1, RW), `discrete` (FC2, RO), `holding` (FC3, RW), `input` (FC4, RO) |
| `address` | Адрес регистра (десятичный) |
| `format` | `u8`, `s8`, `u16`, `s16`, `u32`, `s32`, `u64`, `s64`, `bcd16`, `bcd32`, `bcd64`, `float`, `double`, `string`, `varstring` |
| `scale` | Множитель `value = raw * scale` |
| `offset` | Прибавляется после scale |
| `round_to` | Округление до N знаков |
| `type` | MQTT-тип контрола: `switch`, `value`, `voltage`, `current`, `power`, `energy_power`, `temperature`, `pressure`, `range`, `text`, `pushbutton` |
| `units` | Единицы (V, A, °C, mWh) |
| `error_value` | Если raw == этому, контрол публикует error |
| `unsupported_value` | Если raw == этому, контрол не публикуется (используется производителем для «нет данных») |
| `read_rate_limit_ms` | Не опрашивать чаще раз в N мс (для медленных регистров) |
| `enabled` | `false` — канал в шаблоне есть, но по умолчанию выключен (включается через UI) |
| `readonly` | `true` — даже если `holding`/`coil`, делать только чтение |
| `sporadic` | `true` — запрашивать только когда драйвер уже есть в опросе (не при первом запуске) |
| `condition` | Выражение на полях `parameters` — канал виден только если истина (см. ниже) |
| `group` | ID группы для UI (см. `groups` ниже) |
| `word_order` | `big_endian` (по умолчанию) или `little_endian` для multi-register значений |

### Endianness

Modbus — big-endian по байту, но для u32/s32/float порядок **слов** (16-битных регистров) часто little-endian у разных производителей. Симптом: значение «как-то странно прыгает» — попробуй `"word_order": "little_endian"` (или большой/малой обратное).

### `string` / `varstring`

```json
{
  "name": "FW Version",
  "reg_type": "input",
  "address": 250,
  "format": "string",
  "size": 8,           // длина в регистрах (= 16 байт)
  "type": "text"
}
```

`varstring` — строка переменной длины с null-terminator.

## `parameters` — настройки прошивки

Регистры, которые UI показывает как «настройки устройства» (а не телеметрия):

```json
"parameters": [
  {
    "id": "in0_mode",
    "title": "Input 0 mode",
    "address": 1100,
    "reg_type": "holding",
    "format": "u16",
    "default": 0,
    "enum": [0, 1, 2, 3],
    "enum_titles": [
      {"en": "Switch"},
      {"en": "Push button"},
      {"en": "RS-trigger"},
      {"en": "Counter"}
    ],
    "group": "g_in0_setup"
  }
]
```

`condition` в channel может смотреть на `id` параметра: `"condition": "in0_mode==3"` — канал виден только если параметр == 3.

## `groups` — группировка UI

```json
"groups": [
  {"id": "g_inputs", "title": "Inputs"},
  {"id": "g_in0_channels", "title": "Input 0", "group": "g_inputs"},
  {"id": "g_in0_setup", "title": "Input 0 setup", "group": "g_inputs"}
]
```

Иерархия: `group` ссылается на `id` родителя. Web UI рисует развёрнутые секции.

## `translations` — i18n

```json
"translations": {
  "ru": {
    "Voltage": "Напряжение",
    "Input 0": "Вход 0",
    "g_inputs": "Входы"
  }
}
```

Web UI показывает переводы по выбранному языку.

## Workflow создания шаблона

### 1. Документация устройства

`WebFetch` мануал производителя — таблица регистров (адреса, типы, scale). Без неё не делай шаблон, угадывание = бесконечная отладка.

### 2. Скопируй похожий встроенный шаблон как стартовый

```bash
ssh root@<HOST> 'cp /usr/share/wb-mqtt-serial/templates/config-wb-mr6c.json /etc/wb-mqtt-serial.conf.d/templates/acme-em100.json'
ssh root@<HOST> 'vi /etc/wb-mqtt-serial.conf.d/templates/acme-em100.json'   # правь под своё устройство
```

Минимум: поменяй `device_type`, `device.id`, `device.name`, `title`, потом перепиши `channels` под свою таблицу регистров.

### 3. Тест на одном канале

Сначала шаблон с **одним** каналом. Добавь устройство в `/etc/wb-mqtt-serial.conf` через confed, проверь что канал публикуется и значение правдоподобное:

```bash
ssh root@<HOST> "mosquitto_sub -t '/devices/<device.id>_<slave_id>/controls/<channel>' -C 1 -W 5"
```

Если значение не совпадает с ожиданием — `format`, `scale`, `word_order` подкручивай. Прямой контрольный замер через `modbus_client_rpc`:

```bash
ssh root@<HOST> 'modbus_client_rpc -m rtu -a <slave> -t 4 -r <addr> -c <count> -b <baud> -s 2 -p N <port>'
```

(`-t 4` = `input registers`, FC4. См. `/troubleshooting-serial`.)

### 4. Расширь под все каналы

Добавляй пачками по 5-10, после каждой — проверка через MQTT.

### 5. Параметры и группы

Когда базовая телеметрия работает — добавь `parameters` для настроек, `groups` для UI.

### 6. Шаблон в Git/бэкап

Кастомный шаблон не переживёт FIT — обязательно в `/controller-backup` (он сам подберёт `/etc/wb-mqtt-serial.conf.d/`).

## Загрузка / тест без рестарта

```bash
ssh root@<HOST> 'systemctl restart wb-mqtt-serial'
```

Логи парсинга шаблона:

```bash
ssh root@<HOST> 'journalctl -u wb-mqtt-serial -n 50 --no-pager | grep -iE "(template|<device.id>)"'
```

Ошибки типа `Failed to parse template` / `Unknown register type` — синтаксис.

## Пример: 1-фазный счётчик энергии

Возьмём гипотетический ACME EM-100 со следующей таблицей:

| Адрес | Регистр | Формат | Scale | Что |
|-------|---------|--------|-------|-----|
| 0-1 | input | u32 | 0.1 | Voltage (mV→V) |
| 2-3 | input | u32 | 0.001 | Current (mA→A) |
| 4-5 | input | s32 | 0.01 | Active power (W) |
| 6-7 | input | u32 | 0.001 | Active energy (Wh→kWh) |

```json
{
  "title": "ACME EM-100",
  "device_type": "ACME-EM100",
  "group": "g_energy_meters",
  "device": {
    "name": "ACME EM-100",
    "id": "acme-em100",
    "channels": [
      {"name": "Voltage", "reg_type": "input", "address": 0, "format": "u32", "scale": 0.1, "type": "voltage", "units": "V"},
      {"name": "Current", "reg_type": "input", "address": 2, "format": "u32", "scale": 0.001, "type": "current", "units": "A"},
      {"name": "Active Power", "reg_type": "input", "address": 4, "format": "s32", "scale": 0.01, "type": "power", "units": "W"},
      {"name": "Active Energy", "reg_type": "input", "address": 6, "format": "u32", "scale": 0.001, "type": "energy_power", "units": "kWh"}
    ]
  }
}
```

## Грабли

- **Шаблон в `/usr/share/wb-mqtt-serial/templates/`** — затрётся при апгрейде. Только `/etc/wb-mqtt-serial.conf.d/templates/`.
- **Endianness** — самая частая ошибка для u32/s32/float. Если значение прыгает 65535-кратно — `word_order: little_endian`.
- **Scale в обратную сторону** — производители иногда дают «raw / 10», а не «raw × 0.1». Тест на одном канале решает.
- **Дубликат `device_type`** — если одинаковый с пакетным, переопределит молча. Префикс типа `ACME-` помогает.
- **Кириллица в `device.id`** — нельзя (пойдёт в имя топика). Только `[a-z0-9-]`.
- **Адрес 0-based vs 1-based** — Modbus-стандарт 0-based, многие мануалы дают 1-based (FFFF=65535 → 1-based 1, 0-based 0). Смотри в спеке устройства какая нумерация.
- **Без `error_value`** — если устройство возвращает FFFF при «нет данных», MQTT покажет 65535 как валидное значение.

## Документация

- Documentation — формат шаблона: <https://github.com/wirenboard/wb-mqtt-serial/blob/master/docs/template.md>
- Modbus FC: <https://modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf>
- Примеры — `/usr/share/wb-mqtt-serial/templates/` на контроллере (250+ шаблонов).
