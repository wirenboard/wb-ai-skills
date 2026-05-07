---
name: wiren-board
description: Управление контроллерами Wiren Board через MCP-сервер wiren-board. Подключай при любой работе с контроллерами WB.
allowed-tools: Bash Read Write Grep Glob WebFetch WebSearch
---

# wiren-board (MCP)

Мастер-скилл для работы с контроллерами Wiren Board через MCP-tools `wb_*`. Все операции с контроллером — через MCP, а не напрямую через `ssh`/`mosquitto_*`/`avahi-browse`. Подгружай при любом упоминании контроллеров WB, MQTT-топиков, устройств на шине, правил автоматизации, конфигурации оборудования.

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Найти контроллеры в сети | `wb_discover` (mDNS + ручные) |
| Доступность контроллера + системная инфа | `wb_probe` |
| Добавить контроллер вручную (нет mDNS, есть IP) | `wb_add_controller` |
| Команда на контроллере (быстрая, до 2 мин) | `wb_ssh_exec` |
| Долгая команда (`apt`, `docker pull/build`, `wb-release`) | `wb_ssh_exec_async` → `wb_job_status` / `wb_job_tail` / `wb_job_cancel` |
| Прочитать файл (до 64 КБ) | `wb_read_file` |
| Записать файл (SFTP) | `wb_write_file` |
| Чтение retained-топика | `wb_mqtt_read` |
| Запись в MQTT (контрол → `<topic>/on`) | `wb_mqtt_write` |
| Список топиков по префиксу | `wb_mqtt_list` |
| MQTT RPC (wb-mqtt-serial, confed, wbrules, db_logger) | `wb_mqtt_rpc` |
| Список устройств / контролов | `wb_mqtt_devices`, `wb_mqtt_controls` |
| История значения | `wb_history` |
| SVG-чарт истории (line/bar/area/heatmap…) | `wb_history_chart` |
| Аудит / снимок состояния | `wb_audit`, `wb_state_save`, `wb_state_diff` |
| Метрики (load/RAM/диск), логи unit'а, failed-сервисы | `wb_metrics`, `wb_logs`, `wb_failed` |
| Modbus: шаблон / список шаблонов / прошивка / probe / порты / scan / авто-добавить | `wb_modbus_template`, `wb_modbus_templates_list`, `wb_modbus_device_info`, `wb_modbus_probe`, `wb_modbus_ports`, `wb_modbus_scan`, `wb_modbus_add_devices` |
| Modbus serial debug (raw RS-485 пакеты) | `wb_serial_debug` |
| wb-rules: list / load / save / disable / delete | `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_disable`, `wb_rules_delete` |
| Confed: load / save | `wb_confed_load`, `wb_confed_save` |

## Обнаружение контроллеров

`wb_discover` — единственный путь. Внутри объединяет mDNS-скан (через `bonjour-service` + `avahi-browse`) и ручные добавления (`wb_add_controller`). Возвращает `sn`, `host`, адреса, `reachable`, `fw`. Не дёргай `avahi-browse`/`ping` руками.

**Холодный кеш — норма.** Discovery опрашивает сеть каждые `WB_DISCOVERY_INTERVAL` мс (default 15000). Если контроллер только что появился или MCP-сервер только что запустился, первый `wb_discover` может вернуть пустой список или неполный. Подожди ~5-15 сек и повтори.

Если контроллер совсем не виден через mDNS (Docker-окружение, закрытый multicast, разные VLAN):

- `wb_add_controller` с `host=<IP-или-hostname>` — заведёт запись, попробует получить SN.

Адреса, которые возвращает `wb_discover`, не содержат IPv6 link-local (`fe80::*`) — для SSH с этого хоста они всё равно бесполезны без указания scope-id.

### Формат серийного номера

- SN — буквенно-цифровой, вида `A25NDEMJ` (длина может отличаться).
- Hostname: `wirenboard-<sn>.local`.
- Все tools принимают `sn`; mDNS-резолвинг внутри.
- Получить SN с контроллера руками (если не удалось через discovery): `wb_ssh_exec` `cat /var/lib/wirenboard/short_sn.conf` или `wb_mqtt_read` `/devices/system/controls/Short SN`.

### Версия прошивки

- Через `wb_probe` — приходит в системной инфе.
- Прямые файлы при необходимости: `wb_read_file` `/etc/wb-fw-version` (формат — timestamp `YYYYMMDDHHMM`) и `/usr/lib/wb-release` (shell-нотация: `RELEASE_NAME`, `SUITE`, `TARGET`).

## Команды на контроллере

### Быстрые (до 2 минут)

`wb_ssh_exec` с `sn` и `cmd`. Tool работает через пул соединений и отдаёт stdout/stderr/exit_code.

Примеры команд (что класть в `cmd`):

- `systemctl is-active wb-mqtt-serial`
- `df -h / /mnt/data`
- `uptime; free -h`
- `ls /dev/ttyRS485-* /dev/ttyMOD* 2>/dev/null`

### Длинные (apt, tar, сборка, wb-release)

**Только** через `wb_ssh_exec_async`. Синхронный `wb_ssh_exec` упадёт по таймауту, оборвав apt в середине транзакции.

Цикл:

1. `wb_ssh_exec_async` `cmd="..."` → возвращает `job_id`.
2. `wb_job_tail` `job_id=...` → инкрементальный лог (вызывай с интервалом).
3. `wb_job_status` `job_id=...` → `running` / `exited` (`exit_code`).
4. `wb_job_cancel` `job_id=...` — если нужно отменить (только до критической фазы установки).

Внутри tool использует systemd-run, задача переживает разрыв соединения.

## MQTT-операции

### Чтение и запись

| Сценарий | Tool |
|----------|------|
| Прочитать значение контрола | `wb_mqtt_read` topic=`/devices/<d>/controls/<c>` |
| Прочитать тип/meta | `wb_mqtt_read` topic=`/devices/<d>/controls/<c>/meta/type` |
| Записать значение контрола | `wb_mqtt_write` topic=`/devices/<d>/controls/<c>/on` value=`...` |
| Список устройств | `wb_mqtt_devices` или `wb_mqtt_list` `prefix=/devices/+/meta/name` |
| Список контролов устройства | `wb_mqtt_controls` или `wb_mqtt_list` `prefix=/devices/<d>/controls/+` |

**Важно:** для управления контролами публикуй в `<topic>/on`, не в сам `<topic>` — иначе значение затрётся драйвером.

### MQTT RPC

`wb_mqtt_rpc` инкапсулирует генерацию client_id, подписку на reply-топик, паузу до публикации запроса и таймаут. Не пиши `mosquitto_sub`/`mosquitto_pub` вручную для стандартных сервисов.

Параметры: `service` (например `wb-mqtt-serial`), `method` (`config/Load`), `params` (объект, обязательный — даже пустой `{}`), `timeout` (сек, по умолчанию разумный для метода).

Для специализированных операций есть высокоуровневые tools — предпочитай их:

| Цель | Tool |
|------|------|
| Список доступных шаблонов | `wb_modbus_templates_list` (без filter — сводка по группам, с filter — flat list) |
| Содержимое шаблона устройства (по device_type или mqtt-id, регистронезависимо) | `wb_modbus_template` |
| Параметры прошивки устройства (fw, model, parameters) | `wb_modbus_device_info` |
| Пинг устройства на шине | `wb_modbus_probe` |
| Параметры RS-485 портов | `wb_modbus_ports` |
| Сканирование шины | `wb_modbus_scan` (через wb-device-manager, async; `scan_type:"extended"`=Fast Modbus, `"standard"`=обычный) |
| Добавить найденное сканом в конфиг | `wb_modbus_add_devices` (по одному, dryRun=true для предпросмотра) |
| Raw RS-485 debug-логи драйвера | `wb_serial_debug` |
| Прочитать `/etc/wb-mqtt-serial.conf` или `/etc/wb-hardware.conf` | `wb_confed_load` |
| Записать конфиг с валидацией и рестартом | `wb_confed_save` |
| Список / load / save / disable / delete правил | `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_disable`, `wb_rules_delete` |

`wb_mqtt_rpc` нужен для редких/нестандартных вызовов (например `db_logger`, ручные сервисы).

### Доступные RPC-сервисы (через `wb_mqtt_rpc` или специализированные tools)

#### wb-mqtt-serial — драйвер Modbus/RS-485

| Метод | Tool | params |
|-------|------|--------|
| `config/Load` | `wb_mqtt_rpc` или `wb_confed_load(path=/etc/wb-mqtt-serial.conf)` | `{}` |
| `device/LoadConfig` | `wb_modbus_template` | `{device_id:"wb-mr6c_138"}` или полный набор по адресу |
| `device/Probe` | `wb_modbus_probe` | `{path,baud_rate,slave_id}` |
| `port/Scan` | `wb_modbus_scan` | `{path,baud_rate,mode:"all"}` (5-30 сек, у tool правильный таймаут внутри) |
| `ports/Load` | `wb_modbus_ports` | `{}` |

#### confed — редактор конфигов

| Метод | Tool | Назначение |
|-------|------|-----------|
| `Editor/Load` | `wb_confed_load` | Загрузить конфиг по path |
| `Editor/Save` | `wb_confed_save` | Сохранить (валидация JSON + атомарный рестарт сервиса) |

**Используй `wb_confed_save` вместо `wb_write_file`** для `/etc/wb-mqtt-serial.conf`, `/etc/wb-hardware.conf`, `/etc/wb-mqtt-mbgate.conf` и т.п. — он валидирует JSON и атомарно перезапускает зависимый сервис. Прямая запись битого JSON через `wb_write_file` может остановить опрос шины.

#### wbrules — движок правил

| Метод | Tool |
|-------|------|
| `Editor/List` | `wb_rules_list` |
| `Editor/Load` | `wb_rules_load` |
| `Editor/Save` | `wb_rules_save` (валидация JS + горячая перезагрузка) |
| Удаление | `wb_rules_delete` (только с явным OK) |

## Файловые операции

| Действие | Tool |
|----------|------|
| Прочитать файл (≤64 КБ) | `wb_read_file` |
| Записать файл (SFTP, любого размера в пределах диска) | `wb_write_file` |
| Скачать каталог рекурсивно | вне MCP — локальный `scp -r root@<host>:<dir> <local>` |
| Загрузить каталог рекурсивно | вне MCP — локальный `scp -r <local> root@<host>:<dir>` |

`scp` для каталогов делается через локальный Bash в обход MCP, потому что tool `wb_write_file` работает с одним файлом за вызов.

Для записи многих мелких конфигов (например, при восстановлении бэкапа) используй `wb_write_file` в цикле или `wb_ssh_exec_async` `cmd='tar -xzf /tmp/backup.tar.gz -C /'`.

## Правила безопасности

### ЗАПРЕЩЕНО

- **НЕ запускать FIT-прошивку** (`wb-fw-update`, `swupdate`, `wb-run-update`, `fit-update`) — прошивка только через web UI контроллера. FIT перезаписывает rootfs целиком, ошибка может окирпичить контроллер.
- **`wb-factoryreset` — только с явным подтверждением пользователя и обязательным бэкапом перед.** Стирает все пользовательские данные (конфиги, правила, шаблоны, Docker-образы), пароль root возвращается к `wirenboard`, кастомные SSH-ключи пропадают. Полный сценарий — в `/controller-update` (Сценарий D). Не запускай по неоднозначной формулировке («очисти», «сброс»).

### Бэкап перед правкой конфигов — ОБЯЗАТЕЛЬНО

Перед любой записью в конфигурационный файл:

```
wb_ssh_exec sn=<SN> cmd='cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)'
```

Файлы, требующие бэкапа: `wb-mqtt-serial.conf`, `wb-hardware.conf`, файлы в `/etc/network/`, `/etc/mosquitto/`, `/etc/wb-rules/`.

### RPC/специализированные tools вместо прямой правки

| Конфиг | Tool | Почему |
|--------|------|--------|
| `/etc/wb-mqtt-serial.conf` | `wb_confed_save` | Валидация JSON + атомарный рестарт драйвера |
| Правила `/etc/wb-rules/*.js` | `wb_rules_save` | Валидация JS + горячая перезагрузка |
| `/etc/wb-hardware.conf` | `wb_confed_save` | Валидация + применение без reboot |

### Подтверждение пользователя

**Спрашивай подтверждение перед:**
- Деструктивными операциями: `rm`, `reboot`, `dpkg --remove`, `apt-get purge`, `wb_rules_delete`.
- Перезапуском критичных сервисов: `systemctl restart wb-mqtt-serial`, `systemctl restart mosquitto`.
- Изменением сетевой конфигурации (можно потерять доступ).
- Остановкой Docker-контейнеров.

**БЕЗ подтверждения (выполняй сразу):**
- Диагностика и чтение: `wb_metrics`, `wb_logs`, `wb_failed`, `wb_mqtt_read`, `wb_mqtt_list`, `wb_audit`, `wb_modbus_*` read-only методы.
- Сканирование шины (`wb_modbus_scan`) — read-only для устройств.
- Просмотр правил/конфигов (`wb_rules_load`, `wb_confed_load`).

### Логи — только свежие

Через `wb_logs` укажи разумный `since` или `lines`. Не вытаскивай весь журнал — у unit'ов на контроллерах он может быть большим.

## Типовые диагностические сценарии

| Сценарий | Tools |
|---------|-------|
| Упавшие сервисы | `wb_failed` |
| Место и нагрузка | `wb_metrics` |
| Ошибки в журнале | `wb_logs` `priority=err` (или `wb_ssh_exec` `journalctl -p err -n 50 --no-pager`) |
| Kernel mismatch | `wb_audit` отметит расхождение или `wb_ssh_exec` `uname -r; dpkg -l linux-image-wb*` |
| Список serial-портов | `wb_ssh_exec` `ls /dev/ttyRS485-* /dev/ttyMOD* 2>/dev/null` |
| Жив ли MQTT-брокер | `wb_mqtt_list` (если возвращает топики — брокер живой), при сомнении `wb_logs unit=mosquitto` |

## Скиллы

Доступные скиллы для специфических задач — вызывай `/skill-name` когда задача попадает в их область:

| Скилл | Область |
|-------|---------|
| `/wb-mqtt-serial` | Конфигурация Modbus-устройств, включение/отключение каналов, добавление устройств |
| `/serial-templates` | Создание собственных Modbus-шаблонов (когда родного нет) |
| `/wb-rules` | JS-правила автоматизации (defineRule, виртуальные устройства, таймеры, cron) |
| `/scenarios` | Декларативные сценарии Web UI (devicesControl, lightControl, thermostat, schedule) |
| `/notifications` | Telegram/Email/SMS из правил (`Notify.*`), `alarms.conf` |
| `/troubleshooting` | Общая диагностика: упавшие сервисы, место на диске, kernel mismatch, Docker |
| `/troubleshooting-serial` | RS-485/Modbus: CRC-ошибки, таймауты, проблемы сигнала |
| `/services` | systemd: override-conf, drop-ins, custom units/timers, mask/unmask |
| `/network` | NetworkManager + wb-connection-manager: ethernet/wifi/4G/OpenVPN, failover |
| `/wb-cloud` | Wiren Board Cloud agent: активация, статус, отвязка |
| `/mqtt-broker` | mosquitto admin: пользователи, ACL, мосты, TLS |
| `/controller-backup` | Полный бэкап: конфиги, пакеты, данные, Docker volumes |
| `/controller-update` | Обновление прошивки и пакетов |
| `/hardware-modules` | Модули расширения (MOD1-MOD4): Zigbee, CAN, RS-485, релейные |
| `/software-install` | Установка ПО: Docker, Zigbee2MQTT, Home Assistant, Node-RED, Grafana |
| `/zigbee` | Zigbee-устройства: сопряжение, управление, группы, OTA |
| `/history` | История данных, графики (`wb_history_chart`), экспорт |
| `/bugreport` | Составление багрепорта с диагностическим архивом |

`/diagrams` (Mermaid) и `/documentation-search` есть только в bash-флейворе — они не зависят от контроллера, MCP-двойник не имеет смысла. Если установлены параллельно из `skills/bash/` — будут доступны.

## Принципы работы

1. **Сначала диагностика, потом действия.** Прежде чем что-то менять — разберись в текущем состоянии. `wb_confed_load`, `wb_logs`, `wb_mqtt_read`/`wb_mqtt_list`, `wb_metrics`.

2. **Не угадывай имена топиков.** Имена устройств и контролов зависят от конфигурации конкретного контроллера. Сначала `wb_mqtt_devices` / `wb_mqtt_controls`.

3. **Не спрашивай «хотите ли вы» — делай.** Пользователь остановит, если что. Исключение — деструктивные операции (см. правила безопасности).

4. **Действуй автономно.** Проверяй факты через tools, не спрашивай «установлен ли X?» — выясни сам:
   - `wb_ssh_exec` `dpkg -l | grep docker`
   - `wb_ssh_exec` `ip addr show`
   - `wb_audit` для общей картины

5. **Шаблоны и конфиги — с контроллера, не из интернета.** На железке актуальная версия под установленную прошивку. Не делай WebFetch шаблонов с GitHub — используй `wb_modbus_template`.

6. **Документация — перед починкой.** Для типовых задач (Docker, Zigbee, Home Assistant) сначала прочитай соответствующую страницу вики через WebFetch: `https://wirenboard.com/wiki/<Тема>`.
