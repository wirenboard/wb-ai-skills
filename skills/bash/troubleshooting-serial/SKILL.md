---
name: troubleshooting-serial
description: "Программная диагностика serial-шины (RS-485, Modbus) на контроллере Wiren Board. Ошибки CRC, таймауты, устройство не отвечает, медленный опрос, debug-логи, сканирование шины, проверка здоровья устройств."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# troubleshooting-serial

Программная диагностика serial-шины (RS-485, Modbus и другие протоколы) с уровня драйвера и MQTT. Подгружай при: ошибках Modbus, CRC, таймаутах, «устройство не отвечает», «данные не обновляются», медленном опросе, ошибках чтения/записи.

**ВАЖНО: Действуй без пауз. НЕ спрашивай разрешение на каждый шаг — пользователь УЖЕ попросил диагностику, это и есть подтверждение. Выполняй ВСЕ шаги подряд: логи -> debug -> scan -> здоровье. НЕ останавливайся с вопросами «хотите запустить debug?» или «если хочешь, я могу...» — просто делай. Отчёт — в конце.**

**Переменная HOST:** во всех примерах ниже `<HOST>` означает `wirenboard-<SN>.local`, где `<SN>` — серийный номер контроллера (например `wirenboard-AABBCCDD.local`). Подставляй реальный адрес.

## MQTT RPC через Bash — базовый паттерн

```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/<driver>/<service>/<method>/$CID/reply" -C 1 -W <timeout> & sleep 0.2; mosquitto_pub -t "/rpc/v1/<driver>/<service>/<method>/$CID" -m '"'"'{"id":1,"params":{...}}'"'"'; wait'
```

## Начни с этого

1. **Документация по устройству** — всегда показывай URL источника. Последовательность:
   - `WebFetch("https://wirenboard.com/wiki/<DeviceModel>")` — страница устройства, раздел «Известные неисправности»
   - Если ничего не нашёл там — сразу пробуй веб-поиск по вики (домен менялся, пробуй оба): `WebSearch("site:wirenboard.com/wiki/ <DeviceModel> <ошибка>")` или `WebSearch("site:wiki.wirenboard.com <DeviceModel> <ошибка>")`
   - Смотри changelog устройства (`WebFetch` страницы changelog) — там часто есть ERRMODBUS-коды и исправленные баги
   - **Всегда цитируй URL**, откуда взял информацию

2. Жив ли драйвер:
   ```bash
   ssh root@<HOST> "systemctl is-active wb-mqtt-serial"
   ```

3. Логи — масштаб и тип. Сначала общий счётчик и последние строки (не сужай regex'ом — пропустишь шумные шаблоны вроде `[mqtt] connection lost`, `[serial client] Reading events failed`, `[backend] Unable to cleanup topic`, у которых нет `device modbus:N`):
   ```bash
   ssh root@<HOST> "journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | wc -l; echo ---; journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | tail -30"
   ```
   Гистограмма по slave_id (как дополнение к выводу выше, не вместо):
   ```bash
   ssh root@<HOST> "journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | grep -oP 'device modbus:\\K\\d+' | sort | uniq -c | sort -rn"
   ```

4. **Debug — raw-пакеты. ВЫПОЛНЯЙ СРАЗУ, НЕ СПРАШИВАЯ.** Это безопасная операция — скрипт сам включает и выключает debug, сам перезапускает драйвер. **Это исключение** из общего правила «спрашивай перед `systemctl restart wb-mqtt-serial`» (мастер-скилл): два рестарта внутри debug-сессии входят в саму процедуру и идут без подтверждения.

   Время debug: раздели 18000 на количество ошибок за час (из шага 3). Результат — секунды. Минимум 30, максимум 300. Если ошибок 0 или их единицы (<10/h) — ставь 120 сек: проблема редкая или транзиентная, длинный debug всё равно ничего не покажет.

   Таблица:
   - <10 ошибок/час → 120 сек (низкая частота, длинный сбор не нужен)
   - 10 ошибок/час → 18000/10 = 1800 → cap 300 сек
   - 50 ошибок/час → 360 → cap 300 сек
   - 100 ошибок/час → 180 сек
   - 500 ошибок/час → 36 сек
   - 1000+ ошибок/час → 18 → floor 30 сек

   **Скрипт debug-сбора** — пишем на контроллер один раз, потом запускаем фоновой задачей. Защищён от незавершённого выхода: если что-то упадёт в середине, `trap ... EXIT` гарантированно вернёт `debug:false` и рестартанёт драйвер. **Не убирай `trap` — без него повисший рестарт оставит контроллер в режиме debug, забивая диск.**

   ```bash
   ssh root@<HOST> 'cat > /tmp/debug-serial.sh << '"'"'SCRIPT'"'"'
   #!/bin/bash
   set -e
   DURATION="${1:-120}"
   CONF=/etc/wb-mqtt-serial.conf
   LOG=/mnt/data/ai/wb-ai-integration/diag/debug-serial.log
   mkdir -p /mnt/data/ai/wb-ai-integration/diag

   # Captured-group regex — сохраняет исходное форматирование (отступы, пробелы вокруг :)
   restore_debug_off() {
     sed -i '"'"'s/\("debug"\s*:\s*\)true/\1false/'"'"' "$CONF"
     systemctl restart wb-mqtt-serial >/dev/null 2>&1 || true
     echo "[debug-serial] restored debug:false"
   }
   trap restore_debug_off EXIT INT TERM

   sed -i '"'"'s/\("debug"\s*:\s*\)false/\1true/'"'"' "$CONF"
   systemctl restart wb-mqtt-serial
   sleep 1
   START_TS=$(date -u +%Y-%m-%dT%H:%M:%S)
   echo "[debug-serial] collecting ${DURATION}s from $START_TS"
   sleep "$DURATION"
   # Без -n: пишем весь журнал за окно (на 120с при debug=true это ~3000 строк, -n 500 truncate'ит молча).
   journalctl -u wb-mqtt-serial --since "$START_TS" --no-pager > "$LOG"
   echo "[debug-serial] saved $(wc -l < "$LOG") lines to $LOG"
   SCRIPT
   chmod +x /tmp/debug-serial.sh'
   ```

   Запуск фоновой задачи (`<DURATION>` — рассчитанное значение, по умолчанию 120):
   ```bash
   ssh root@<HOST> 'systemd-run --unit=wb-ai-job-$(cat /dev/urandom | tr -dc a-z0-9 | head -c8) --collect bash /tmp/debug-serial.sh <DURATION>'
   ```

   Дождись завершения (`systemctl is-active wb-ai-job-...` → `inactive`, либо `journalctl -u wb-ai-job-... -n 5`). Забери лог:
   ```bash
   scp root@<HOST>:/mnt/data/ai/wb-ai-integration/diag/debug-serial.log /tmp/debug-serial.log
   ```
   (Локальный путь — `/tmp/debug-serial.log` или другой явный, не `./` — у тебя нет стабильного cwd между вызовами.)

   **Сразу проверь, что debug действительно выключен:**
   ```bash
   ssh root@<HOST> 'grep -c "\"debug\"\s*:\s*false" /etc/wb-mqtt-serial.conf; systemctl is-active wb-mqtt-serial'
   ```
   Должно быть `1` и `active`. Если `debug:true` остался — немедленно `trap`-пути не сработали; подключайся и руками: `sed -i '"'"'s/\("debug"\s*:\s*\)true/\1false/'"'"' /etc/wb-mqtt-serial.conf && systemctl restart wb-mqtt-serial`.

   Если за 2 минуты ошибка не воспроизвелась — скажи пользователю: проблема редкая, debug выключен.

5. **Scan шины** — кто есть, кого нет, дубликаты. Сначала узнай параметры портов:
   ```bash
   ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/ports/Load/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/ports/Load/$CID" -m '"'"'{"id":1,"params":{}}'"'"'; wait'
   ```

   `ports/Load` возвращает только **активные** порты (которые драйвер сейчас открывает), а не все физические `/dev/ttyRS485-*` и `/dev/ttyMOD*`. Если хочешь полный список — `ls /dev/ttyRS485-* /dev/ttyMOD*`.

   Затем запусти скан через `wb-device-manager/bus-scan/Start` (асинхронно, прогресс/devices в retained `/wb-device-manager/state`):
   ```bash
   # Старт (Start не ждёт окончания)
   ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-device-manager/bus-scan/Start/$CID/reply" -C 1 -W 10 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-device-manager/bus-scan/Start/$CID" -m '"'"'{"id":1,"params":{"scan_type":"extended","preserve_old_results":false,"port":{"path":"/dev/ttyRS485-1","baud_rate":<реальный>,"parity":"N","data_bits":8,"stop_bits":2}}}'"'"'; wait'

   # Polling до scanning:false
   ssh root@<HOST> 'for i in $(seq 1 60); do s=$(mosquitto_sub -t /wb-device-manager/state -C 1 -W 2); echo "$s" | jq -e ".scanning == false" >/dev/null && break; sleep 2; done; mosquitto_sub -t /wb-device-manager/state -C 1 -W 3 | jq ".devices"'
   ```

   `scan_type:"extended"` — Fast Modbus (WB+Onokom). `scan_type:"standard"` — обычный Modbus, видит сторонние устройства. Стороннее без полной поддержки — точечно через `modbus_client_rpc`. Если устройство есть в `config/Load`, но нет в результате скана — **обязательно** проверь его через `device/Probe` прежде чем делать вывод «оно умерло» (баг наблюдался на WB-MAP6S через старый `port/Scan`).

6. **Здоровье WB-устройств** — uptime + питание (если регистр маппится в напряжение):
   ```bash
   # Uptime (рег. 104-105) — у всех WB-устройств с прошивкой WB-MS-protocol:
   ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t 3 -r 104 -c 2 -b <baud> -s <stop> -p <parity> <path>"
   # Vsupply / Vmin (рег. 121-122, мВ) — на реле/диммерах/MCM, на MAI/MAP/MR3 могут маппиться по-другому:
   ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t 3 -r 121 -c 2 -b <baud> -s <stop> -p <parity> <path>"
   ```
   **Регистры 121-122 не универсальны** — на WB-MAI6/WB-MAP6S и некоторых MR3 они могут отдавать вход/измерение, а не Vsupply. Если значение явно неправдоподобно для напряжения (5В, доли вольта при 24В питании) — для этой модели регистр другой; смотри страницу устройства на вики.

7. **Сохрани отчёт на контроллер:**
   ```bash
   echo '<текст отчёта>' | ssh root@<HOST> 'cat > /mnt/data/ai/wb-ai-integration/diag/serial-diag.txt'
   ```

## Версия прошивки устройства

Если нужна версия прошивки конкретного WB-устройства — **не спрашивай пользователя**, делай так:

1. Загрузи конфиг драйвера:
   ```bash
   ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/config/Load/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/config/Load/$CID" -m '"'"'{"id":1,"params":{}}'"'"'; wait'
   ```
2. Найди устройство по slave_id, запомни его `device_type` (например `WB-MDM3`).
3. Прочитай шаблон **из файла** на контроллере (`templates/GetTemplate` RPC на текущих прошивках не работает — даёт таймаут):
   ```bash
   ssh root@<HOST> 'for f in /usr/share/wb-mqtt-serial/templates/*.json; do dt=$(jq -r ".device_type // \"\"" "$f" 2>/dev/null); [ "$dt" = "<device_type>" ] && jq ".device.channels[] | {name, enabled}" "$f" && break; done'
   ```
4. В выводе найди канал, у которого имя похоже на версию прошивки: `FW Version`, `Firmware Version`, `SW Version`, `Serial` и т.п.
5. В конфиге драйвера найди этот канал у нужного устройства и включи: `"enabled": true`. Если канала нет в `channels` — добавь.
6. Сохрани конфиг через `confed/Editor/Save` (см. скилл `wb-mqtt-serial`, раздел про `content:($c|fromjson)` — content должен быть **JSON-объектом**, не сериализованной строкой).
7. Через 10-20 секунд прочитай значение из MQTT:
   ```bash
   ssh root@<HOST> "mosquitto_sub -t '/devices/<device_id>/controls/<channel_name>' -C 1 -W 20"
   ```

Пример: у `wb-mdm3_57` канал называется `FW Version`. У другого устройства — может быть иначе, всегда смотри в шаблоне.

## Паттерны: увидел -> делай

| Увидел | Делай |
|---|---|
| `invalid crc` в логах | Debug -> смотри raw-пакет. CRC битый = помехи/контакт. Чужой slave_id = дубликат |
| `request timed out` | `device/Probe` -> живо ли. Если молчит — физика, питание, slave_id |
| `invalid data size` | Scan -> ищи дубликат slave_id. Debug -> лишние байты = коллизия |
| `rate limit exceeded` | Разнести устройства по портам, увеличить baud, отключить лишние каналы |
| Устройство в scan но не в конфиге | Может мешать! Добавить или отключить физически |
| Устройство в конфиге но не в scan | Выключено, обрыв, или стороннее (scan не видит) |
| CRC у всех устройств | Помехи, терминатор 120 Ом, заземление. Эксперимент: снизить скорость |
| CRC у одного | Подключить коротким проводом. Если заработает — линия |
| Другие stop bits помогают | Несовпадение параметров порта и устройства |
| Мин. напряжение < 20В (рег. 122) | Просадки питания -> блок питания, сечение провода |
| Маленький uptime (рег. 104-105) | Устройство перезагружалось -> питание |
| Exception code в debug | 1=illegal FC, 2=illegal addr, 3=illegal value, 4=device failure |
| Протокол не Modbus в конфиге | modbus_client_rpc и scan не помогут, только логи и debug |

## Инструменты

**modbus_client_rpc** (приоритет) — через очередь драйвера, безопасен:
```bash
ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t <FC> -r <reg> -c <count> -b <baud> -s <stop> -p <parity> <port>"
```
FC: 1=coils, 2=discrete, 3=holding, 4=input, 5=write coil, 6=write reg, 15=write coils, 16=write regs.

**device/Probe** — быстрая проверка "живо ли":
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/device/Probe/$CID/reply" -C 1 -W 10 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/device/Probe/$CID" -m '"'"'{"id":1,"params":{"path":"/dev/ttyRS485-1","baud_rate":9600,"data_bits":8,"parity":"N","stop_bits":2,"slave_id":<ID>,"total_timeout":10000}}'"'"'; wait'
```

**ports/Load** — параметры портов:
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/ports/Load/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/ports/Load/$CID" -m '"'"'{"id":1,"params":{}}'"'"'; wait'
```

**wb-modbus-scanner** — Fast Modbus утилита (WB, Onokom). `apt install wb-modbus-ext-scanner`. Конфликтует с драйвером — требует остановки wb-mqtt-serial (согласуй с пользователем!).
```bash
ssh root@<HOST> "wb-modbus-scanner -d <port> -b <baud>"        # scan
ssh root@<HOST> "wb-modbus-scanner -d <port> -s <sn> -i <id>"  # смена slave_id
```

**modbus_client** — прямой доступ. Конфликтует с драйвером — требует остановки wb-mqtt-serial (согласуй с пользователем!).

## Полезные регистры WB-устройств

| Регистр | Что | Формат |
|---|---|---|
| 104-105 | Uptime | u32, секунды (универсально для всех WB-устройств) |
| 110 | Baud rate | u16, сокращённо: 96=9600, 1152=115200 |
| 121 | Напряжение питания | u16, мВ — **только реле/диммеры/MCM** (на MAI/MAP/MR3 регистр маппится в иное измерение) |
| 122 | Мин. напряжение | u16, мВ (с момента загрузки) — там же где 121 |
| 128 | Slave ID | u16 |
| 200-205 | Модель | string |
| 270-271 | Серийный номер | u32 |

Broadcast запись (slave_id 0) — сменить baud/адрес всем WB на шине разом.

baud_rate `1152` = `115200` — сокращённая запись, НЕ ошибка.

## Эксперименты (бэкап + согласование с пользователем)

Перед экспериментами:
```bash
ssh root@<HOST> "cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)"
```

- **Stop bits**: попробовать 1 и 2 через `modbus_client_rpc -s 1` / `-s 2`
- **Скорость**: broadcast `modbus_client_rpc -a 0 -t 6 -r 110 ... 96` -> смена порта через confed. Пропали ошибки = кабель/терминация
- **Изоляция**: `config/Load` -> `"enabled": false` -> `confed/Editor/Save`. Пропали ошибки у остальных = это устройство мешает
- **Таймауты**: `response_timeout_ms`, `guard_interval_us` в конфиге порта

**Всё вернуть обратно после экспериментов.**

## Грабли

- `modbus_client`/`wb-modbus-scanner` без остановки драйвера -> ложные ошибки
- Debug забыт -> диск заполнится
- port/Scan -> только WB и Onokom
- Неправильный baud -> молчит СОВСЕМ. Неправильные stop bits -> плавающие ошибки
- RS-485 звездой работает на коротких расстояниях; при проблемах — рекомендуй цепочку

## Документация

- <https://wiki.wirenboard.com/wiki/RS-485>
- <https://wiki.wirenboard.com/wiki/Modbus>
- <https://wiki.wirenboard.com/wiki/Common_Modbus_Registers>
- <https://wiki.wirenboard.com/wiki/How_to_diagnose>
- <https://github.com/wirenboard/wb-modbus-ext-scanner/blob/main/docs/protocol.ru.md>
