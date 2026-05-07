---
name: hardware-modules
description: Настройка модулей расширения WB (MOD1-4, WBIO, RS-485, Zigbee, CAN) через MCP — wb_confed_load/save для /etc/wb-hardware.conf.
allowed-tools: Bash Read Write WebFetch
---

# hardware-modules (MCP)

Настройка внутренних модулей расширения контроллера Wiren Board через MCP-tools `wb_confed_*`.

## Архитектура

- **Конфиг:** `/etc/wb-hardware.conf` (JSON).
- **Сервис:** `wb-hwconf-manager` — применяет Device Tree overlays.
- **Правка:** через `wb_confed_save` (не пиши файл напрямую через `wb_write_file` — `wb_confed_save` валидирует и атомарно перезапускает зависимые сервисы).

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Прочитать `/etc/wb-hardware.conf` (с JSON Schema) | `wb_confed_load path=/etc/wb-hardware.conf` |
| Записать конфиг (валидация + применение) | `wb_confed_save` |
| Какие порты появились (`/dev/ttyMODn`, `/dev/ttyRS485-n`) | `wb_ssh_exec` `ls -la /dev/ttyMOD* /dev/ttyRS485-*` |
| Логи драйвера модуля | `wb_logs unit=<unit>` |
| Состояние сервисов после смены | `wb_failed` |

## Слоты

Точный набор зависит от платформы (wb6/wb7/wb8) и ревизии — **бери из `schema`**, возвращаемой `wb_confed_load`. Типовая картина:

| Слот в `content` | Что это | Возможный port |
|------------------|---------|----------------|
| `mod1`..`modN` или `wb84-mod1`..`wb84-mod3` | Внутренние слоты UART/GPIO. Часть UART-only, часть GPIO-only | `/dev/ttyMOD<N>` если модуль UART (Zigbee, CAN-UART, RS-485, RS-232, GPS) |
| `wb84-rs485-1`, `wb84-rs485-2` | Встроенные RS-485 с терминатором | `/dev/ttyRS485-1`, `/dev/ttyRS485-2` |
| `wb84-extio1`..`wb84-extio8` | GPIO для WBIO-модулей (реле, сухие контакты, SSR) | — (нет tty) |
| `wb84-w1`, `wb84-w2` | Клеммы W1/W2 в режиме 1-Wire master | — (через w1-bus) |
| `wb84-wbmz5` | Слот резервного питания БРП | — |
| `wb72-wbc` | Слот модема | — (modem) |

Префикс ID (`wb84-*` для wb8 и т.п.) меняется между ревизиями — не закладывайся на него, выбирай по `schema.title`/`description`.

## Чтение конфигурации

`wb_confed_load path=/etc/wb-hardware.conf` возвращает `configPath`, `content` (объект конфига) и `schema` (JSON Schema со всеми модулями). Из schema берут точные ID модулей для текущей ревизии платы.

## Установка модуля

**Шаг 0:** Спроси пользователя, в какой слот вставлен модуль физически. Не выбирай сам!

**Шаг 1:** `wb_confed_load` — определи допустимое значение `module` из `schema`. Человекочитаемое описание модуля — в `content.modules[].description`.

Реальные ID с прошивок wb-2507/wb8 — для ориентира, **не копировать вслепую**:

| Модуль | module ID (примеры) |
|--------|---------------------|
| Zigbee | `wbe2r-r-zigbee` |
| RS-232 | `wbe2-i-rs232` |
| RS-485 (встроенные) | `wb67-can-rs485` |
| RS-485 (внешний слот, изолированный) | `wbe2-i-rs485-iso` |
| CAN | `wb67-can`, `wbe-i-can-iso`, `wb67-can-uart` |
| 1-Wire | `wb6-wx-1wire` |

> Точные ID зависят от платформы и ревизии. **Всегда** бери из `schema` ответа — у разных ревизий разные пакеты `wbe2-*` / `wb67-*` / `wb84-*`.

**Шаг 2:** Измени `content` — в нужном слоте установи `module`. Сохрани:

```
wb_confed_save sn=<SN> path=/etc/wb-hardware.conf content=<полный JSON>
```

**Шаг 3:** Проверь — но только если устанавливаешь UART-модуль (Zigbee/CAN-UART/RS-232/RS-485/GPS):

```
wb_ssh_exec sn=<SN> cmd='ls -la /dev/ttyMOD<N>'
```

Для GPIO/1-Wire/extio/WBMZ5/модема порта `/dev/ttyMOD*` не появится — это **нормально**, не путай с ошибкой установки. Для 1-Wire — `wb_ssh_exec` `ls /sys/bus/w1/devices/`. Для extio/WBIO — `wb_mqtt_devices` (новое устройство появится в `/devices/+/meta/name`).

И в любом случае — `wb_failed` чтобы убедиться, что зависимые сервисы не упали.

**Шаг 4:** Смена профиля MOD1-4 может потребовать **перезагрузки контроллера** — `wb_confed_save` рестарт `wb-hwconf-manager` не всегда покрывает применение нового overlay. Если порт не появился — предупреди пользователя и предложи `reboot` (с подтверждением).

## Грабли

- **Не пиши `/etc/wb-hardware.conf` через `wb_write_file`** — только `wb_confed_save`. Битый JSON может оставить контроллер без сети после рестарта `wb-hwconf-manager`.
- **ID модулей** зависят от ревизии — всегда бери из `schema`, не из памяти.
- После установки Zigbee → настрой zigbee2mqtt (`/software-install`).
- Смена модуля в слоте — старый деинициализируется, устройства пропадут.

## Документация

- <https://wiki.wirenboard.com/wiki/Internal_modules>
- <https://wiki.wirenboard.com/wiki/WBIO>
