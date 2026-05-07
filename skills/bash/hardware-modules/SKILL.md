---
name: hardware-modules
description: Настройка модулей расширения WB (MOD1-4, WBIO, RS-485, Zigbee, CAN) через confed RPC.
allowed-tools: Bash Read Write WebFetch
---

# hardware-modules

Настройка внутренних модулей расширения контроллера Wiren Board.

## Архитектура

- **Конфиг:** `/etc/wb-hardware.conf` (JSON)
- **Сервис:** `wb-hwconf-manager` — применяет Device Tree overlays
- **Правка:** через confed RPC (не правь файл напрямую!)

## Слоты

Точный набор слотов зависит от платформы (wb6/wb7/wb8) и ревизии. **Бери из `schema` ответа `Editor/Load`** — он отражает реальное железо. Типовая картина:

| Слот в `content` | Что это | Возможный port |
|------------------|---------|----------------|
| `wb84-mod1`..`wb84-mod3` (на wb8) или `mod1`..`mod4` (на wb7) | Внутренние слоты UART/GPIO. Часть слотов — UART-only, часть — GPIO-only (например `wb84-mod1` без UART) | `/dev/ttyMOD<N>` если модуль UART (Zigbee, CAN-UART, RS-485, RS-232, GPS) |
| `wb84-rs485-1`, `wb84-rs485-2` | Встроенные RS-485 с терминатором | `/dev/ttyRS485-1`, `/dev/ttyRS485-2` |
| `wb84-extio1`..`wb84-extio8` | GPIO для WBIO-модулей (реле, сухие контакты, SSR) | — (нет tty) |
| `wb84-w1`, `wb84-w2` | Клеммы W1/W2 в режиме 1-Wire master | — (через w1-bus, не tty) |
| `wb84-wbmz5` | Слот резервного питания БРП | — |
| `wb72-wbc` | Слот модема (на платформах с поддержкой) | — (modem) |

Префикс (`wb84-*` для wb8, без префикса для wb7 и т.п.) меняется между ревизиями — не закладывайся на конкретный ID, выбирай по `schema.title` / `description`.

## Чтение конфигурации

```bash
# Загрузить текущий конфиг + схему через confed RPC
ssh root@<HOST> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/confed/Editor/Load/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/confed/Editor/Load/${ID}" -m "{\"id\":\"${ID}\",\"params\":{\"path\":\"/etc/wb-hardware.conf\"}}"
  wait $SUB_PID
'
```

Ответ содержит `configPath`, `content` (объект конфига) и `schema` (JSON Schema со всеми модулями).

## Установка модуля

**Шаг 0:** Спроси пользователя в какой слот вставлен модуль физически. Не выбирай сам!

**Шаг 1:** Прочитай конфиг (выше) — определи `module` из `schema`. Человекочитаемое описание — в `content.modules[].description` (не в `schema.definitions`, там только техническая дискриминация по `id`).

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

**Шаг 2:** Измени `content` — в нужном слоте установи `module`. Сохрани через confed:

```bash
ssh root@<HOST> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/confed/Editor/Save/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/confed/Editor/Save/${ID}" -m "{\"id\":\"${ID}\",\"params\":{\"path\":\"/etc/wb-hardware.conf\",\"content\":<полный JSON>}}"
  wait $SUB_PID
'
```

**Шаг 3:** Проверь — но только если устанавливаешь UART-модуль (Zigbee/CAN-UART/RS-232/RS-485/GPS):
```bash
ssh root@<HOST> 'ls -la /dev/ttyMOD<N>'
```
Для GPIO/1-Wire/extio/WBMZ5/модема порта `/dev/ttyMOD*` не появится — это **нормально**, не путай с ошибкой установки. Для 1-Wire — проверка через `ls /sys/bus/w1/devices/`. Для extio/WBIO — через `mosquitto_sub /devices/+/meta/name` (появится новое устройство в MQTT).

## Грабли

- **Не правь `/etc/wb-hardware.conf` через ssh напрямую** — только confed RPC
- **ID модулей** зависят от ревизии — всегда бери из schema
- После установки Zigbee → настрой zigbee2mqtt (`/software-install`)
- Смена модуля в слоте — старый деинициализируется, устройства пропадут

## Документация

- <https://wiki.wirenboard.com/wiki/Internal_modules>
- <https://wiki.wirenboard.com/wiki/WBIO>
