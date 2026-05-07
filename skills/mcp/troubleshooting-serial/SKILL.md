---
name: troubleshooting-serial
description: "Программная диагностика serial-шины (RS-485, Modbus) на контроллере Wiren Board через MCP. Ошибки CRC, таймауты, устройство не отвечает, медленный опрос, debug-логи, сканирование шины, проверка здоровья устройств."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# troubleshooting-serial (MCP)

Программная диагностика serial-шины (RS-485, Modbus и другие протоколы) с уровня драйвера и MQTT через MCP-tools `wb_*`. Подгружай при: ошибках Modbus, CRC, таймаутах, «устройство не отвечает», «данные не обновляются», медленном опросе, ошибках чтения/записи.

**ВАЖНО: Действуй без пауз. НЕ спрашивай разрешение на каждый шаг — пользователь УЖЕ попросил диагностику, это и есть подтверждение. Выполняй ВСЕ шаги подряд: логи → debug → scan → здоровье. НЕ останавливайся с вопросами «хотите запустить debug?» или «если хочешь, я могу...» — просто делай. Отчёт — в конце.**

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Сбор raw RS-485 пакетов (включает debug, рестартует драйвер, выключает) | `wb_serial_debug` |
| Жив ли slave_id (быстрая проверка) | `wb_modbus_probe` |
| Что видит на шине (extended=Fast Modbus, standard=обычный для сторонних) | `wb_modbus_scan` (async через wb-device-manager) |
| Параметры портов (baud, parity, stop) | `wb_modbus_ports` |
| Шаблон устройства (для имени канала FW Version) | `wb_modbus_template` |
| Текущий конфиг для сверки или правки | `wb_confed_load`, `wb_confed_save` |
| Логи драйвера | `wb_logs` `unit=wb-mqtt-serial` |
| Чтение/запись регистров вне очереди драйвера (требует stop wb-mqtt-serial) | `wb_ssh_exec` `modbus_client` / `wb-modbus-scanner` |
| Чтение регистров через очередь драйвера (безопасно) | `wb_ssh_exec` `modbus_client_rpc` |
| Прочитать значение канала из MQTT | `wb_mqtt_read` |

## Начни с этого

1. **Документация по устройству** — всегда показывай URL источника. Последовательность:
   - `WebFetch("https://wirenboard.com/wiki/<DeviceModel>")` — страница устройства, раздел «Известные неисправности».
   - Если ничего не нашёл там — `WebSearch("site:wirenboard.com/wiki/ <DeviceModel> <ошибка>")` или `WebSearch("site:wiki.wirenboard.com <DeviceModel> <ошибка>")`.
   - Смотри changelog устройства (`WebFetch` страницы changelog) — там часто есть ERRMODBUS-коды и исправленные баги.
   - **Всегда цитируй URL**, откуда взял информацию.

2. Жив ли драйвер: `wb_ssh_exec` `systemctl is-active wb-mqtt-serial` (или `wb_failed` — если в списке, всё плохо).

3. Логи — масштаб + последние строки + гистограмма по slave_id (regex `device modbus:\\K\\d+` пропускает `[mqtt] connection lost`, `[serial client] Reading events failed` и т.п. — поэтому ВМЕСТЕ с гистограммой нужны и сырые последние строки):

   ```
   wb_logs sn=<SN> unit=wb-mqtt-serial priority=warning lines=30
   wb_ssh_exec sn=<SN> cmd='journalctl -u wb-mqtt-serial -p warning --since "1 hour ago" --no-pager | grep -oP "device modbus:\\K\\d+" | sort | uniq -c | sort -rn'
   ```

   `wb_logs` сам не принимает `since` — окно времени задавай через `journalctl --since` в `wb_ssh_exec`. Для последних N строк — `wb_logs lines=N`.

4. **Debug — raw-пакеты. ВЫПОЛНЯЙ СРАЗУ, НЕ СПРАШИВАЯ.** Это безопасная операция — `wb_serial_debug` атомарно включает debug в `/etc/wb-mqtt-serial.conf`, рестартует драйвер, собирает journalctl за окно, **гарантированно** через `trap` возвращает `debug:false` и рестартует обратно (даже при ошибке посередине). Это **исключение** из общего правила «спрашивать перед рестартом wb-mqtt-serial» — рестарты входят в саму процедуру.

   Время debug: раздели 18000 на количество ошибок за час (из шага 3). Минимум 30, максимум 300 секунд. Если ошибок <10/час — ставь 120 (длинный сбор всё равно ничего не покажет на редких/транзиентных проблемах).

   Таблица:
   - <10 ошибок/час → 120 сек
   - 10/час → 18000/10 = 1800 → cap 300
   - 50/час → 360 → cap 300
   - 100/час → 180
   - 500/час → 36
   - 1000+/час → 18 → floor 30

   ```
   wb_serial_debug sn=<SN> duration=<DURATION>
   ```

   Tool возвращает `{jobId, logPath: /mnt/data/ai/wb-ai-integration/diag/debug-serial.log, message}`. Прогресс — `wb_job_status` / `wb_job_tail`. После завершения:

   ```
   wb_read_file sn=<SN> path=/mnt/data/ai/wb-ai-integration/diag/debug-serial.log
   ```

   Если лог большой (>64 КБ) — `wb_read_file` упадёт; тогда `scp` локально вне MCP. **Сразу после tool'а проверь, что debug действительно выключен и драйвер живой:**

   ```
   wb_ssh_exec sn=<SN> cmd='grep -c "\"debug\":\\s*false" /etc/wb-mqtt-serial.conf; systemctl is-active wb-mqtt-serial'
   ```

   Должно быть `1` и `active`. Если `debug:true` остался (trap не сработал) — `wb_ssh_exec_async` `python3 -c "import json; c=json.load(open('/etc/wb-mqtt-serial.conf')); c['debug']=False; json.dump(c, open('/etc/wb-mqtt-serial.conf','w'), indent=2)" && systemctl restart wb-mqtt-serial`.

   Если за 2 минуты ошибка не воспроизвелась — скажи пользователю: проблема редкая, debug выключен.

5. **Scan шины** — кто есть, кого нет, дубликаты.

   - `wb_modbus_ports` — узнать параметры **активных** портов (не все физические `/dev/ttyRS485-*`/`/dev/ttyMOD*`, а только те, что драйвер сейчас открывает по конфигу).
   - `wb_modbus_scan path=<port> baud_rate=<baud> mode=all` — Fast Modbus scan. Параметры порта берёшь из `wb_modbus_ports` под конкретный path. Находит **только WB и Onokom**. Стороннее не видно. **Также может молча пропускать живые WB-устройства** (наблюдалось на WB-MAP6S — устройство опрашивается, MQTT-каналы обновляются, но scan его не видит; `wb_modbus_probe` тут же находит). Если устройство есть в `wb_confed_load`, но нет в `wb_modbus_scan` — обязательно проверь `wb_modbus_probe` прежде чем делать вывод «оно умерло».

6. **Здоровье WB-устройств** — uptime, при необходимости питание. Через `modbus_client_rpc` (безопасно, идёт через очередь драйвера):

   ```
   wb_ssh_exec sn=<SN> cmd='modbus_client_rpc -m rtu -a <slave> -t 3 -r 104 -c 2 -b <baud> -s <stop> -p <parity> <path>'
   wb_ssh_exec sn=<SN> cmd='modbus_client_rpc -m rtu -a <slave> -t 3 -r 121 -c 2 -b <baud> -s <stop> -p <parity> <path>'
   ```

   104-105 — uptime (u32, сек). 121-122 — Vsupply / Vmin (u16, мВ) **только** на реле/диммерах/MCM. На WB-MAI/WB-MAP/некоторых MR3 эти регистры маппятся по-другому (вход/измерение). Если значение неправдоподобно для напряжения (5В при 24В питании) — для этой модели регистр другой; см. страницу устройства на вики.

7. **Сохрани отчёт** — `wb_write_file` `/mnt/data/ai/wb-ai-integration/diag/serial-diag.txt` с текстом отчёта.

## Версия прошивки устройства

Если нужна версия прошивки конкретного WB-устройства — **не спрашивай пользователя**, делай так:

1. `wb_confed_load` `/etc/wb-mqtt-serial.conf` — найди устройство по slave_id, запомни `device_type` (например `WB-MDM3`).
2. `wb_modbus_template device_type=<тип>` — посмотри шаблон. (Tool принимает только `device_type`/`mqtt-id`, регистронезависимо. `wb_modbus_device_info` — для текущих параметров прошивки по `device_id`.)
3. Среди каналов шаблона найди тот, у кого название напоминает версию прошивки: `FW Version`, `Firmware Version`, `SW Version`, `Serial` и т.п. — имя может быть любым, ищи по смыслу.
4. В конфиге драйвера найди этот канал у нужного устройства и выстави `"enabled": true`.
5. `wb_confed_save` с обновлённым полным конфигом.
6. `wb_mqtt_read` `/devices/<device_id>/controls/<channel_name>` (timeout 20 сек, чтобы дождаться публикации после рестарта).

Пример: у `wb-mdm3_57` канал называется `FW Version`, у другого устройства может быть иначе — всегда смотри в шаблоне.

## Паттерны: увидел → делай

| Увидел | Делай |
|--------|-------|
| `invalid crc` в логах | `wb_serial_debug` → смотри raw-пакет. CRC битый = помехи/контакт. Чужой slave_id = дубликат |
| `request timed out` | `wb_modbus_probe` → живо ли. Если молчит — физика, питание, slave_id |
| `invalid data size` | `wb_modbus_scan` → ищи дубликат slave_id. `wb_serial_debug` → лишние байты = коллизия |
| `rate limit exceeded` | Разнести устройства по портам, увеличить baud, отключить лишние каналы |
| Устройство в scan, но не в конфиге | Может мешать! Добавить или отключить физически |
| Устройство в конфиге, но не в scan | Выключено, обрыв, или стороннее (scan не видит) |
| CRC у всех устройств | Помехи, терминатор 120 Ом, заземление. Эксперимент: снизить скорость |
| CRC у одного | Подключить коротким проводом. Если заработает — линия |
| Другие stop bits помогают | Несовпадение параметров порта и устройства |
| Мин. напряжение < 20В (рег. 122) | Просадки питания → блок питания, сечение провода |
| Маленький uptime (рег. 104-105) | Устройство перезагружалось → питание |
| Exception code в debug | 1=illegal FC, 2=illegal addr, 3=illegal value, 4=device failure |
| Протокол не Modbus в конфиге | `modbus_client_rpc` и scan не помогут, только логи и debug |

## Инструменты

**modbus_client_rpc** (приоритет) — через очередь драйвера, безопасен. Запускай через `wb_ssh_exec`:

```
wb_ssh_exec sn=<SN> cmd='modbus_client_rpc -m rtu -a <slave> -t <FC> -r <reg> -c <count> -b <baud> -s <stop> -p <parity> <port>'
```

FC: 1=coils, 2=discrete, 3=holding, 4=input, 5=write coil, 6=write reg, 15=write coils, 16=write regs.

**`wb_modbus_probe`** — быстрая проверка «живо ли».

**`wb_modbus_ports`** — параметры портов.

**wb-modbus-scanner** — Fast Modbus утилита (WB, Onokom). `wb_ssh_exec` `apt install wb-modbus-ext-scanner` (если не установлена). Конфликтует с драйвером — требует остановки `wb-mqtt-serial` (согласуй с пользователем!).

```
wb_ssh_exec sn=<SN> cmd='systemctl stop wb-mqtt-serial && wb-modbus-scanner -d <port> -b <baud>; systemctl start wb-mqtt-serial'
```

**modbus_client** — прямой доступ. Конфликтует с драйвером — тоже требует остановки `wb-mqtt-serial`.

## Полезные регистры WB-устройств

| Регистр | Что | Формат |
|---------|-----|--------|
| 104-105 | Uptime | u32, секунды (универсально) |
| 110 | Baud rate | u16, сокращённо: 96=9600, 1152=115200 |
| 121 | Напряжение питания | u16, мВ — **только реле/диммеры/MCM** (на MAI/MAP/MR3 другой маппинг) |
| 122 | Мин. напряжение | u16, мВ — там же где 121 |
| 128 | Slave ID | u16 |
| 200-205 | Модель | string |
| 270-271 | Серийный номер | u32 |

Broadcast запись (slave_id 0) — сменить baud/адрес всем WB на шине разом.

baud_rate `1152` = `115200` — сокращённая запись, НЕ ошибка.

## Эксперименты (бэкап + согласование с пользователем)

Перед экспериментами:

```
wb_ssh_exec sn=<SN> cmd='cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)'
```

- **Stop bits**: попробовать 1 и 2 через `modbus_client_rpc -s 1` / `-s 2`.
- **Скорость**: broadcast `modbus_client_rpc -a 0 -t 6 -r 110 ... 96` → смена порта через `wb_confed_save`. Пропали ошибки = кабель/терминация.
- **Изоляция**: `wb_confed_load` → `"enabled": false` для подозрительного устройства → `wb_confed_save`. Пропали ошибки у остальных = это устройство мешает.
- **Таймауты**: `response_timeout_ms`, `guard_interval_us` в конфиге порта.

**Всё вернуть обратно после экспериментов.**

## Грабли

- `modbus_client`/`wb-modbus-scanner` без остановки драйвера → ложные ошибки.
- Debug забыт — `wb_serial_debug` сам выключает и возвращает конфиг; не дёргай через `wb_confed_save` руками.
- `wb_modbus_scan` → только WB и Onokom.
- Неправильный baud → молчит СОВСЕМ. Неправильные stop bits → плавающие ошибки.
- RS-485 звездой работает на коротких расстояниях; при проблемах — рекомендуй цепочку.

## Документация

- <https://wiki.wirenboard.com/wiki/RS-485>
- <https://wiki.wirenboard.com/wiki/Modbus>
- <https://wiki.wirenboard.com/wiki/Common_Modbus_Registers>
- <https://wiki.wirenboard.com/wiki/How_to_diagnose>
- <https://github.com/wirenboard/wb-modbus-ext-scanner/blob/main/docs/protocol.ru.md>
