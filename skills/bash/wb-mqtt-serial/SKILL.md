---
name: wb-mqtt-serial
description: "Драйвер Modbus/RS-485 на контроллере Wiren Board. Конфиг /etc/wb-mqtt-serial.conf, шаблоны, доступ через MQTT RPC. Включение/отключение каналов, добавление устройств, сканирование шины, правка конфигурации wb-mqtt-serial."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-mqtt-serial

Драйвер Modbus/RS-485. Конфиг `/etc/wb-mqtt-serial.conf`, шаблоны `/usr/share/wb-mqtt-serial/templates/` (пакетные, не трогай) и `/etc/wb-mqtt-serial.conf.d/templates/` (свои). Доступ через MQTT RPC `wb-mqtt-serial/...`, не через файлы. Подгружай на: «канал не публикуется», «не вижу устройство на шине», «опрос замер», «включи канал X», «просканируй шину», «slave_id / холдинг / coil / input регистр», включение/отключение каналов, добавление/удаление/правка устройств в конфиге wb-mqtt-serial, «добавь modbus-устройство», «удали устройство», «очисти список устройств», «измени конфиг serial», «wb-mqtt-serial.conf», правка ports/devices в конфиге.

**Граница скиллов:** если нужно создать шаблон для устройства которого нет во встроенных — это скилл `wb-mqtt-serial-template`. Если проблема с сигналом/CRC/таймаутами — `troubleshooting-serial`.

**Переменная HOST:** во всех примерах ниже `<HOST>` означает `wirenboard-<SN>.local`, где `<SN>` — серийный номер контроллера (например `wirenboard-AABBCCDD.local`). Подставляй реальный адрес.

## RPC и файлы — что откуда брать

| Что | Откуда | Почему |
|-----|--------|--------|
| Все каналы устройства, включая `enabled:false` | **Файл** `/usr/share/wb-mqtt-serial/templates/config-<device.id>.json` | На текущих прошивках (wb-2602, wb-2507) `templates/GetTemplate` RPC **не работает** (таймаут), а `device/LoadConfig` возвращает только `{fw, model, parameters}` без channels |
| Текущий конфиг драйвера | RPC `config/Load` | |
| Параметры прошивки устройства (debounce, modes, in/out mappings) | RPC `device/LoadConfig` | Только `{fw, model, parameters}` |
| Параметры RS-485 портов | RPC `ports/Load` | |
| Запись конфига | RPC `confed/Editor/Save` | Валидация + атомарный рестарт. Битый JSON не пишется, опрос шины жив |
| Сканирование шины | RPC `wb-device-manager/bus-scan/Start` (асинхронно, прогресс/devices в retained `/wb-device-manager/state`) | `scan_type:"extended"` — Fast Modbus, `"standard"` — обычный. Старый `wb-mqtt-serial/port/Scan` молча пропускает живые WB-устройства (баг наблюдался на WB-MAP6S) |
| Точечная проверка slave_id | RPC `device/Probe` | |

Прямой `ssh ... cat >` в `.conf` — только с бэкапом и осознанно (см. ниже).

- **«Канала нет в MQTT» ≠ «не поддерживается».** Многие каналы шаблонов идут с `"enabled": false` (Uptime, Counter, Total, Serial). Сначала прочти шаблон из файла, потом выводы.
- **Шаблон ищи на контроллере, не на GitHub.** На железке — актуальный под прошивку. `WebFetch` шаблонов почти всегда зря.
- **Кастомный шаблон — последнее средство.** Сначала проверь встроенный.
- **Скан асинхронный.** `wb-device-manager/bus-scan/Start` возвращает сразу, прогресс смотри в retained-state.

## MQTT RPC через Bash

Паттерн MQTT RPC на контроллере — подписка на reply, публикация запроса:

```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/<driver>/<service>/<method>/$CID/reply" -C 1 -W <timeout> & sleep 0.2; mosquitto_pub -t "/rpc/v1/<driver>/<service>/<method>/$CID" -m '"'"'{"id":1,"params":{...}}'"'"'; wait'
```

`params` — вложенный объект, обязательное поле (даже пустой `{}`).

### Получение списка каналов устройства (через файл)

Найди шаблон устройства по `device_type` (например `WB-MR6C`):

```bash
# Имя файла = config-<device.id>.json, где device.id — поле из шаблона.
# Простой случай: WB-MR6C → wb-mr6c. Сложный (с пробелами/точками): "WB-MR6C v.3" → wb-mr6cv3.
# Самый надёжный способ — найти по полю device_type:
ssh root@<HOST> 'for f in /usr/share/wb-mqtt-serial/templates/*.json; do dt=$(jq -r ".device_type" "$f" 2>/dev/null); if [ "$dt" = "WB-MR6C" ]; then echo "$f"; break; fi; done'
```

Прочитать каналы:

```bash
ssh root@<HOST> 'jq ".device.channels[] | {name, enabled}" /usr/share/wb-mqtt-serial/templates/config-wb-mr6c.json'
# или весь шаблон целиком:
ssh root@<HOST> 'cat /usr/share/wb-mqtt-serial/templates/config-wb-mr6c.json'
```

Структура шаблона: `{title, device_type, group, hw, device:{name, id, channels:[...], parameters:[...], groups:[...], translations:{}}}`.

### Примеры RPC вызовов

**Параметры прошивки устройства (debounce, modes, mappings) — НЕ каналы:**
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/device/LoadConfig/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/device/LoadConfig/$CID" -m '"'"'{"id":1,"params":{"device_id":"wb-mr6c_138"}}'"'"'; wait'
```

Возвращает `{fw, model, parameters}`. Для WB-MR6C `parameters` — это `in0_mode`, `in0_debounce_ms`, `in1_out1_sp` и пр. **Каналов в ответе нет** — для каналов читай файл-шаблон (см. выше).

**Текущий конфиг драйвера:**
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/config/Load/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/config/Load/$CID" -m '"'"'{"id":1,"params":{}}'"'"'; wait'
```

**Сохранить конфиг (валидация + рестарт):**

⚠️ **Критично:** `content` — это **JSON-объект**, не сериализованная строка. Если передать строку (с экранированными кавычками внутри), `confed/Editor/Save` запишет её в файл буквально как `"{...}"`-литерал, и `wb-mqtt-serial` упадёт с `requires objectValue`, оборвав опрос **всей шины** до восстановления из бэкапа.

```bash
# Подготовь новый конфиг локально на контроллере как файл:
ssh root@<HOST> 'cp /etc/wb-mqtt-serial.conf /tmp/wb-mqtt-serial.conf.new'
# … правишь /tmp/wb-mqtt-serial.conf.new любым способом (jq, sed, awk) …

# Сохрани через RPC: jq -Rs читает файл и кладёт его как JSON-string в поле, потом fromjson превращает в объект:
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); PAYLOAD=$(jq -nc --rawfile c /tmp/wb-mqtt-serial.conf.new "{id:1,params:{path:\"/etc/wb-mqtt-serial.conf\",content:(\$c|fromjson)}}"); mosquitto_sub -t "/rpc/v1/confed/Editor/Save/$CID/reply" -C 1 -W 15 & sleep 0.2; mosquitto_pub -t "/rpc/v1/confed/Editor/Save/$CID" -m "$PAYLOAD"; wait'
```

Ключевая часть payload — `content:($c|fromjson)`: jq берёт содержимое файла как **объект**, а не как строку. Без `fromjson` (то есть `content:$c` или прямая подстановка `"content":"..."`) — словишь bus-down.

После Save проверь, что файл стал именно объектом, а не строкой:

```bash
ssh root@<HOST> 'head -c 50 /etc/wb-mqtt-serial.conf'
# Норм:    {\n    "debug" : false,\n    "ports" ...
# Ошибка:  "{\\n    \\"debug\\": ...    ← так быть не должно
```

Если стало строкой — немедленно откатывай из бэкапа.

**Скан шины (через `wb-device-manager`, асинхронно):**

```bash
# Старт (возвращает сразу)
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-device-manager/bus-scan/Start/$CID/reply" -C 1 -W 10 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-device-manager/bus-scan/Start/$CID" -m '"'"'{"id":1,"params":{"scan_type":"extended","preserve_old_results":false,"port":{"path":"/dev/ttyRS485-1","baud_rate":115200,"parity":"N","data_bits":8,"stop_bits":2}}}'"'"'; wait'

# Polling прогресс из retained-state
ssh root@<HOST> 'for i in $(seq 1 60); do
  s=$(mosquitto_sub -t /wb-device-manager/state -C 1 -W 2)
  echo "$s" | jq -r ".scanning, .progress" | xargs echo
  echo "$s" | jq -e ".scanning == false" >/dev/null && break
  sleep 2
done'

# Финальные devices
ssh root@<HOST> 'mosquitto_sub -t /wb-device-manager/state -C 1 -W 3 | jq ".devices"'
```

`scan_type:"extended"` — Fast Modbus (WB+Onokom, секунды). `scan_type:"standard"` — обычный Modbus (медленнее, но видит сторонние). Перебор baud — повторяй Start с другими параметрами и `preserve_old_results:true`.

**Старый `wb-mqtt-serial/port/Scan` не использовать** — он молча пропускает живые WB-устройства (наблюдалось на WB-MAP6S). Если что-то не нашлось через `bus-scan` — проверяй точечно `device/Probe`.

**Точечная проверка slave_id:**
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/device/Probe/$CID/reply" -C 1 -W 10 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/device/Probe/$CID" -m '"'"'{"id":1,"params":{"path":"/dev/ttyRS485-1","baud_rate":9600,"slave_id":138}}'"'"'; wait'
```

Прочее: `device/Load` — живые значения каналов; `device/Set` — записать `{"channel_name": value}` (только по явной просьбе пользователя).

## Чтение MQTT-топиков

**Прочитать значение канала:**
```bash
ssh root@<HOST> "mosquitto_sub -t '/devices/<device_id>/controls/<channel>' -C 1 -W 5"
```

**Список устройств/топиков:**
```bash
ssh root@<HOST> "mosquitto_sub -t '/devices/+/meta/name' -C 100 -W 3"
```

**Записать значение:**
```bash
ssh root@<HOST> "mosquitto_pub -t '/devices/<device_id>/controls/<channel>/on' -m '<value>'"
```

## Сценарий «включи канал X на устройстве Y»

1. Список устройств: `ssh root@<HOST> "mosquitto_sub -t '/devices/+/meta/name' -C 100 -W 3"` — найди `device_id`.
2. **Список каналов из шаблона** (включая `enabled:false`): `ssh root@<HOST> 'jq ".device.channels[] | {name, enabled}" /usr/share/wb-mqtt-serial/templates/config-<device.id>.json'` — выясни, какие каналы вообще существуют для этого `device_type`.
3. **Бэкап:** `ssh root@<HOST> "cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)"`.
4. `config/Load({})` через RPC → сохрани результат в `/tmp/wb-mqtt-serial.conf.new` на контроллере.
5. Правь JSON — найди устройство в `ports[*].devices[*]`, в его `channels` добавь/обнови запись `{"name": "<имя>", "enabled": true}` (имена каналов берутся из шаблона, шаг 2).
6. Покажи пользователю diff, предупреди про рестарт `wb-mqtt-serial` (опрос замрёт ~5-10 сек).
7. `confed/Editor/Save` с `content:($c|fromjson)` (см. пример выше — обязательно как объект, не строка).
8. Через 10-20 сек: `ssh root@<HOST> "mosquitto_sub -t '/devices/<device_id>/controls/<channel>' -C 1 -W 20"`.

## Сценарий «что подключено на шине»

1. Порты: `ssh root@<HOST> "ls /dev/ttyRS485-* /dev/ttyMOD*"` или из `config/Load.config.ports`.
2. **`wb-device-manager/bus-scan/Start`** на каждом порту с `scan_type:"extended"` (см. выше).
3. После каждого старта — polling `/wb-device-manager/state` пока `scanning:false`.
4. `state.devices` — массив `{title, sn, device_signature, port:{path}, cfg:{slave_id, baud_rate, parity, data_bits, stop_bits}, fw:{version}, online}`.
5. Сравни с `config/Load.config.ports[*].devices` — что уже сконфигурировано, что новое.

## Сценарий «добавить найденные сканером устройства в конфиг»

После `bus-scan` retained `/wb-device-manager/state` содержит `devices[]` с `{device_signature, port.path, cfg.{slave_id,baud_rate,parity,data_bits,stop_bits}}`. Добавлять — **по одному, с подтверждением на каждом шаге**.

Алгоритм (без жёсткого скрипта — следуй по шагам, на каждом покажи пользователю что собираешься сделать):

1. **Прочитай скан-результат**: `mosquitto_sub -t /wb-device-manager/state -C 1 -W 3` (примеры выше). Отбрось устройства с `bootloader_mode:true`.

2. **Получи mapping `signature → device_type`** один раз: вызови `wb-mqtt-serial/config/Load`, в ответе `.result.types[].types[]` каждый шаблон содержит `hw[].signature`. Скан возвращает `device_signature` — найди соответствующий `type` (= `device_type` для конфига).

3. **Покажи пользователю таблицу кандидатов**: `port`, `slave_id`, `device_signature`, `device_type` (если найден), `fw`, `sn`. Параллельно — что уже в конфиге на тех же портах (вызови `confed/Editor/Load /etc/wb-mqtt-serial.conf` → `.result.content.ports[*].devices[*].slave_id`). Согласуй список к добавлению.

4. **Для каждого подтверждённого устройства** — отдельный Load → mutate → Save:
   - `confed/Editor/Load /etc/wb-mqtt-serial.conf` — свежий снимок (между шагами могло измениться).
   - **Прочитай шаблон устройства** (`/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json`) и собери default-значения параметров: `jq -c '[.device.parameters[] | select(.default != null) | {(.id): .default}] | add' <template>`. Это **обязательно** — schema драйвера требует все required-параметры в device-record (типичный кейс: WB-MAI6 `in1_type..in6_type`). Без default'ов конфиг отвергается, опрос всей шины не запускается.
   - В `result.content.ports[]` найди port с нужным `path`. Если `slave_id` уже в его `devices` — пропусти и доложи. Иначе допиши `{device_type, slave_id, enabled:true, ...defaults}` в его `devices`.
   - Покажи мини-diff пользователю (что добавится в этот port).
   - `confed/Editor/Save` с `content` — **JSON-объект, не строка** (формат payload — см. блок «Запись конфига» выше). Confed валидирует и сам рестартует `wb-mqtt-serial`, опрос замрёт ~5-10 сек.
   - Через 10-20 сек проверь публикацию: `mosquitto_sub -t /devices/+/meta/name -C 100 -W 5 | grep <ожидаемое имя>`.
   - Если save упал по validation (`Missing required property '...'`) — посмотри `journalctl -u wb-mqtt-serial -p err --since "1 min ago"` и допиши недостающие параметры.

5. **Не сливай несколько устройств в один Save** — если один из них упадёт по schema-валидации (неизвестный `device_type` или коллизия), остальные тоже не применятся, и придётся диагностировать что именно сломалось.

### Грабли при auto-добавлении

- **`device_signature` без шаблона** — пропускай и докладывай пользователю. Возможно стороннее устройство или новый WB-модуль из testing-релиза, шаблона ещё нет в установленной прошивке.
- **`slave_id` уже сконфигурирован** — конфликт. Сначала переадресуй через `wb-mqtt-serial/device/Setup` (только по явной просьбе пользователя), потом добавляй.
- **`baud_rate` устройства ≠ `port.baud_rate`** — добавление пройдёт, но опроса не будет. Решение через `device/Setup` или сменить baud порта.
- **bootloader_mode: true** — устройство в fw-update, добавлять рано; дождись завершения и пере-сканируй.

## Прямая правка файла — бэкап обязателен

Если без `confed/Editor/Save` (через `ssh ... cat >`) — сначала бэкап, потом `systemctl restart wb-mqtt-serial`:

```bash
ssh root@<HOST> "cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)"
```

## Грабли

- **`confed/Editor/Save` с content как строкой** — кладёт опрос всей шины. `content` всегда объект, не сериализованная строка. См. пример с `jq -nc --rawfile c ... '... content:($c|fromjson) ...'` выше.
- **`device/LoadConfig` ≠ список каналов.** Возвращает `{fw, model, parameters}` — параметры прошивки (debounce, modes, mappings). Каналы — в файле `/usr/share/wb-mqtt-serial/templates/config-*.json`.
- **`templates/GetTemplate` RPC** — на текущих прошивках (wb-2602, wb-2507) не работает (таймаут). Не используй.
- «Канал не поддерживается» по MQTT-листингу без чтения шаблона — см. выше, `enabled:false` не публикуется.
- `WebFetch` шаблона с GitHub вместо чтения файла на контроллере — на железе актуальнее.
- Кастомный шаблон до проверки встроенного.
- Прямой `cat >` в `.conf` без валидации — битый JSON положит опрос шины.
- Правка пакетных шаблонов в `/usr/share/...` — перезапишутся апдейтом. Кастом — только в `/etc/wb-mqtt-serial.conf.d/templates/`.
- `port/Scan` без timeout >= 30 сек — таймаут, частичный ответ.

## Документация

- Wiki: <https://wirenboard.com/wiki/wb-mqtt-serial>
- Исходники + шаблоны: <https://github.com/wirenboard/wb-mqtt-serial>
- Страницы модулей: `https://wirenboard.com/wiki/<Модель>` (WB-MR6C, WB-MSW_v.4 и т.п.)
