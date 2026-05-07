---
name: wiren-board
description: Управление контроллерами Wiren Board через SSH/MQTT. Подключай при любой работе с контроллерами WB.
allowed-tools: Bash Read Write Grep Glob WebFetch WebSearch
---

# wiren-board

Мастер-скилл для работы с контроллерами Wiren Board из Claude Code CLI. Все операции выполняются через Bash: SSH, mosquitto_sub, mosquitto_pub, avahi-browse, scp. Подгружай при любом упоминании контроллеров WB, MQTT-топиков, устройств на шине, правил автоматизации, конфигурации оборудования.

## Обнаружение контроллеров

### mDNS discovery

Контроллеры Wiren Board анонсируются по mDNS, но **не на `_http._tcp`** (распространённое заблуждение — web-сервис на 80 порту они не публикуют). Текущие прошивки публикуют `_workstation._tcp`. Чтобы рецепт пережил смену типа — сканируй все service-types и фильтруй по имени:

```bash
echo "$(timeout 5 avahi-browse -arp 2>/dev/null)" | awk -F';' '$1=="=" && $3=="IPv4" && $7 ~ /^wirenboard-/ {print $7, $8}' | sort -u
```

Флаги: `-a` — все service-types, `-r` — резолвить (имена + адреса), `-p` — parsable. **Без `-t`**, потому что `-t` выходит, как только кеш avahi пуст: на первом холодном запуске демон ещё не получил mDNS-ответы и `-t` отрубит сканирование за миллисекунды до прихода анонсов. `timeout 5` гарантированно даёт avahi 5 секунд на сбор ответов вне зависимости от состояния кеша.

`echo "$(...)"` (а не прямой пайп `timeout 5 avahi-browse ... | awk ...`) — обязателен. При SIGTERM от `timeout` строки в pipe-буфере между `avahi-browse` и `awk` теряются, и рецепт даёт пустой вывод. Command-substitution `$(...)` ждёт полного завершения процесса и захватывает всё, что было записано в stdout до сигнала.

Поля avahi: `$1` — `=` для resolved-записей (`+` = найдено, но не разрешено), `$3` — IPv4/IPv6 (фильтр v4 ради читаемости — IPv6 link-local `fe80::*` для SSH с другого хоста бесполезен), `$7` — FQDN `wirenboard-<SN>.local`, `$8` — IP. `sort -u` снимает дубль от параллельных IPv4/IPv6 анонсов одного хоста.

Вывод: `wirenboard-A25NDEMJ.local 192.168.1.100`.

Если первый запуск пуст — повтори через 2-3 секунды (avahi мог не успеть получить ответы, особенно если демон только что стартовал или интерфейс недавно поднялся).

Если `avahi-browse` ничего не возвращает — проверь живость демона и интерфейсы:

```bash
systemctl is-active avahi-daemon
# Какие service-types вообще видны (если только локальные — multicast блокируется в сети):
avahi-browse -t -a 2>/dev/null | awk '{print $5}' | sort -u
```

Резолв конкретного имени работает в обход browse — глобальный `nsswitch` через `mdns4_minimal`:

```bash
ping -c1 -W2 wirenboard-A25NDEMJ.local 2>/dev/null     # резолвит и пингует
getent hosts wirenboard-A25NDEMJ.local                 # NB: NSS не всегда подхватывает .local — если пусто, всё равно ping/ssh могут резолвить через avahi-resolve
```

Если SN заранее известен, browse не обязателен — иди сразу `ssh root@wirenboard-<SN>.local`.

### Формат серийного номера

- SN — буквенно-цифровой, вида `A25NDEMJ` (длина может отличаться).
- Hostname: `wirenboard-<sn>.local` (например `wirenboard-A25NDEMJ.local`).
- Получить SN с контроллера вручную:

```bash
ssh root@<ip> cat /var/lib/wirenboard/short_sn.conf
# либо через MQTT:
ssh root@<ip> "mosquitto_sub -t '/devices/system/controls/Short SN' -C 1 -W 3"
```

### Определение версии прошивки

```bash
ssh root@<host> cat /etc/wb-fw-version                                    # timestamp YYYYMMDDHHMM
ssh root@<host> "grep -E '^(RELEASE_NAME|SUITE|TARGET)=' /usr/lib/wb-release"   # ключевые поля
ssh root@<host> cat /usr/lib/wb-release                                   # всё целиком
```

`/usr/lib/wb-release` — shell-нотация. Можно сорсить: `eval "$(ssh ... cat /usr/lib/wb-release)"; echo $RELEASE_NAME`. Файл может включать дополнительные поля (`REPO_PREFIX`, `FIRMWARE_COMPATIBLE` и др.) в зависимости от платформы и версии — не полагайся на фиксированное количество строк.

## SSH-доступ

### Базовое подключение

По умолчанию: `ssh root@wirenboard-<sn>.local`, пароль `wirenboard`.

Для избежания интерактивных запросов при первом подключении:

```bash
ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 root@wirenboard-<sn>.local '<команда>'
```

`accept-new` принимает host-key только если хост ещё не известен (а не на каждое подключение, как `StrictHostKeyChecking=no`). После первого раза реальная подмена ключа снова поднимет ошибку — это правильное поведение.

### Неинтерактивная аутентификация (Linux)

Чтобы пакетные операции не упирались в `Permission denied (publickey,password)`, есть два пути:

1. **Разложить публичный ключ один раз** (рекомендуется для постоянной работы):
   ```bash
   ssh-copy-id -o StrictHostKeyChecking=accept-new root@wirenboard-<sn>.local
   ```
   После этого все `ssh root@wirenboard-<sn>.local` идут без пароля.

2. **`sshpass` для разовых сессий** (если ключ разложить нельзя — например, диагностика на чужом контроллере):
   ```bash
   sudo apt install -y sshpass     # один раз
   sshpass -p wirenboard ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 root@<host> '<команда>'
   ```
   Пароль на стандартной прошивке — `wirenboard`. Не записывай в скрипты, передавай через env (`SSHPASS=wirenboard sshpass -e ssh ...`) если нужно.

### mDNS-кеш истекает per-name

Avahi кеширует резолв `wirenboard-<sn>.local` на ограниченное время. После паузы между сессиями `ssh root@wirenboard-A25NDEMJ.local` может упасть с `Could not resolve hostname`, хотя при том же `ping wirenboard-A25NDEMJ.local` всё резолвится. Лекарство — разовый прогон discovery-команды (см. выше) перед серией SSH-операций; она перерезолвит **все** контроллеры в кеше. Альтернатива — обращаться по IP.

### Короткие команды

Выполняются напрямую:

```bash
ssh root@<host> 'systemctl is-active wb-mqtt-serial'
ssh root@<host> 'cat /etc/wb-mqtt-serial.conf'
ssh root@<host> 'df -h / /mnt/data'
```

### Длинные команды (apt, tar, сборка)

Для команд, которые могут выполняться дольше SSH-таймаута, используй nohup:

```bash
ssh root@<host> 'nohup bash -c "apt-get update && apt-get -y install <пакет>" > /tmp/wb-job.log 2>&1 &'
# Через некоторое время проверь результат:
ssh root@<host> cat /tmp/wb-job.log
```

### Фоновые задачи через systemd

Для задач, которые должны пережить разрыв SSH-сессии. **Лучший паттерн — script-file + systemd `StandardOutput=append:`**: команда уезжает в скрипт-файл, systemd сам пишет stdout/stderr в лог. Никаких трюков с `bash -c '{ …; } > LOG 2>&1'` (где `;` редиректил только последнюю команду из цепочки).

```bash
ID=$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' ')
DIR=/mnt/data/ai/wb-ai-integration/jobs
ssh root@<host> bash -s <<EOF
mkdir -p $DIR
cat > $DIR/$ID.sh <<'JOB'
#!/bin/bash
set -o pipefail
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y install docker-ce
JOB
chmod +x $DIR/$ID.sh
date +%s > $DIR/$ID.started
systemd-run --unit=wb-ai-job-$ID --collect --quiet \\
  -p StandardOutput=append:$DIR/$ID.log \\
  -p StandardError=append:$DIR/$ID.log \\
  -p WorkingDirectory=/root \\
  /bin/bash $DIR/$ID.sh
EOF
echo "jobId=$ID"
```

Проверка статуса:

```bash
ssh root@<host> 'systemctl is-active wb-ai-job-<id>; systemctl show wb-ai-job-<id> -p Result,ExecMainStatus --no-pager; tail -30 /mnt/data/ai/wb-ai-integration/jobs/<id>.log'
```

Отмена:

```bash
ssh root@<host> 'systemctl stop wb-ai-job-<id>'
```

## MQTT-операции (через SSH)

Все MQTT-операции выполняются через SSH на контроллере, где работает локальный Mosquitto.

### Чтение retained-значения

```bash
ssh root@<host> "mosquitto_sub -t '/devices/wb-mr6c_7/controls/K1' -C 1 -W 5"
```

Флаги: `-C 1` — получить одно сообщение и выйти, `-W 5` — таймаут 5 секунд (если нет retained — не зависнет).

### Запись значения

```bash
ssh root@<host> "mosquitto_pub -t '/devices/wb-mr6c_7/controls/K1/on' -m '1'"
```

**Важно:** для управления контролами публикуй в `<topic>/on`, не в сам `<topic>` — иначе значение затрётся драйвером.

### Список устройств и топиков

```bash
# Имена всех устройств
ssh root@<host> "mosquitto_sub -t '/devices/+/meta/name' -C 100 -W 3"

# Все контролы конкретного устройства
ssh root@<host> "mosquitto_sub -t '/devices/wb-mr6c_7/controls/+' -C 100 -W 3"

# Тип контрола
ssh root@<host> "mosquitto_sub -t '/devices/wb-mr6c_7/controls/K1/meta/type' -C 1 -W 5"

# Все retained-топики с разделителем TAB между topic и payload (надёжный парсинг)
ssh root@<host> "mosquitto_sub -F '%t\\t%p' -t '/devices/#' -C 500 -W 5"
```

**Имена с пробелами.** Имена устройств и контролов могут содержать пробелы (`CPU Temperature`, `Board Temperature`, `Input 0`, `Input 0 counter` у WB-MR6C). Поэтому:

- При парсинге вывода `mosquitto_sub` **не используй `-v`** (разделитель — пробел) и **не режь по `[/ ]`**. Используй `mosquitto_sub -F '%t\t%p'` и `awk -F'\t'`.
- Топик в кавычках: `mosquitto_sub -t '/devices/wb-mr6c_2/controls/Input 0' -C 1` — single quotes защищают пробел.
- В RPC и JSON — имена ставь дословно: `["wb-mr6c_2", "Input 0 counter"]`, без кавычек/escape.

### MQTT RPC — вызов сервисов контроллера

RPC через MQTT — основной способ управления сервисами Wiren Board (конфигурация Modbus, правила, редактор конфигов). Паттерн:

```bash
ssh root@<host> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/<service>/<method>/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/<service>/<method>/${ID}" -m '"'"'{"id":"'"'"'"$ID"'"'"'","params":<params_json>}'"'"'
  wait $SUB_PID
'
```

**Как это работает:**

1. Генерируется уникальный ID запроса
2. Подписка на топик ответа `/rpc/v1/<service>/<method>/<ID>/reply` запускается в фоне
3. Пауза 0.3 с, чтобы подписка успела установиться
4. Публикация запроса в `/rpc/v1/<service>/<method>/<ID>` с JSON-телом `{"id":"<ID>","params":...}`
5. `wait` ожидает ответ (таймаут задаётся `-W`)

**Экранирование кавычек:** Обрати внимание на `'"'"'` — это способ вставить одинарную кавычку внутри строки в одинарных кавычках bash. Конструкция `'"'"'` означает: закрыть одинарную кавычку, открыть двойную кавычку, вставить одинарную кавычку, закрыть двойную кавычку, открыть одинарную кавычку снова.

### Доступные RPC-сервисы

#### wb-mqtt-serial — драйвер Modbus/RS-485

| Метод | Назначение | Пример params |
|---|---|---|
| `config/Load` | Текущий конфиг драйвера + полный список **types** (шаблонов с `hw[].signature`) | `{}` |
| `device/LoadConfig` | **Параметры прошивки** устройства (`fw`, `model`, `parameters`). **НЕ** возвращает список каналов | `{"device_id":"wb-mr6c_138"}` или `{"path":"/dev/ttyRS485-1","baud_rate":9600,"parity":"N","data_bits":8,"stop_bits":2,"slave_id":138,"device_type":"WB-MR6C"}` |
| `device/Probe` | Проверка присутствия устройства на шине | `{"path":"/dev/ttyRS485-1","baud_rate":9600,"slave_id":138}` |
| `ports/Load` | Список доступных портов | `{}` |

**Сканирование шины — через `wb-device-manager`, не `wb-mqtt-serial/port/Scan`.** Старый `port/Scan` молча пропускает живые WB-устройства (наблюдалось на WB-MAP6S). Новый интерфейс асинхронный, с retained-state:

| Метод | Назначение | params |
|---|---|---|
| `wb-device-manager / bus-scan / Start` | Запустить сканирование | `{"scan_type":"extended","preserve_old_results":false,"port":{"path":"/dev/ttyRS485-1","baud_rate":115200,"parity":"N","data_bits":8,"stop_bits":2}}` |
| `wb-device-manager / bus-scan / Stop` | Прервать | `{}` |
| Прогресс/результат | retained `/wb-device-manager/state` | `{"scanning":bool,"progress":0..100,"devices":[...]}` |

`scan_type:"extended"` = Fast Modbus (WB+Onokom, секунды). `scan_type:"standard"` = обычный Modbus (медленнее, видит сторонние).

> Список **каналов** устройства (с `enabled:false`-каналами) на текущих прошивках **не возвращается** ни одним RPC-методом. Читай напрямую файл-шаблон: `cat /usr/share/wb-mqtt-serial/templates/config-<device.id>.json`. Метод `templates/GetTemplate` объявлен, но в wb-2602/wb-2507 даёт таймаут — не использовать.

Пример — загрузить конфиг wb-mqtt-serial:

```bash
ssh root@<host> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/config/Load/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/config/Load/${ID}" -m '"'"'{"id":"'"'"'"$ID"'"'"'","params":{}}'"'"'
  wait $SUB_PID
'
```

Пример — сканирование порта (через wb-device-manager, асинхронно):

```bash
# 1. Запустить скан (Start не ждёт окончания, прогресс через retained-state)
ssh root@<host> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/wb-device-manager/bus-scan/Start/${ID}/reply" -C 1 -W 10 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/wb-device-manager/bus-scan/Start/${ID}" -m '"'"'{"id":1,"params":{"scan_type":"extended","preserve_old_results":false,"port":{"path":"/dev/ttyRS485-1","baud_rate":115200,"parity":"N","data_bits":8,"stop_bits":2}}}'"'"'
  wait $SUB_PID
'

# 2. Дождаться scanning:false (polling retained-state)
ssh root@<host> 'for i in $(seq 1 60); do
  s=$(mosquitto_sub -t /wb-device-manager/state -C 1 -W 2)
  echo "$s" | jq -r ".scanning, .progress" | xargs echo
  echo "$s" | jq -e ".scanning == false" >/dev/null && break
  sleep 2
done'

# 3. Забрать devices из state
ssh root@<host> 'mosquitto_sub -t /wb-device-manager/state -C 1 -W 3 | jq ".devices"'
```

**Не использовать `wb-mqtt-serial/port/Scan`** — он молча пропускает живые WB-устройства (наблюдалось на WB-MAP6S). Только `wb-device-manager/bus-scan/Start` (см. выше).

#### confed — редактор конфигов

| Метод | Назначение | Пример params |
|---|---|---|
| `Editor/Load` | Загрузить конфиг | `{"path":"/etc/wb-mqtt-serial.conf"}` |
| `Editor/Save` | Сохранить конфиг (с валидацией и рестартом сервиса) | `{"path":"/etc/wb-mqtt-serial.conf","content":"<полный JSON>"}` |

**Используй `confed/Editor/Save` вместо прямой записи в файлы конфигов** — он валидирует JSON и атомарно перезапускает зависимый сервис. Прямая запись битого JSON может остановить опрос шины.

#### wbrules — движок правил

| Метод | Назначение | Пример params |
|---|---|---|
| `Editor/List` | Список файлов правил с `{enabled, virtualPath, rules, devices, timers}` | `{}` |
| `Editor/Load` | Прочитать файл правила | `{"path":"wb-la-climate.js"}` |
| `Editor/Save` | Сохранить правило (валидация JS + reload) | `{"path":"wb-la-climate.js","content":"<JS-код>"}` |
| `Editor/Remove` | Удалить файл правила | `{"path":"wb-la-climate.js"}` → `{"result":true}` |
| `Editor/ChangeState` | Выключить (`<name>.js` → `<name>.js.disabled`) или включить файл целиком | `{"path":"wb-la-climate.js","enabled":false}` (включение обратно через `enabled:true` ненадёжно — см. скилл `wb-rules`) |
| `Editor/Rename` | Переименовать файл (не тестировался) | `{...}` |

Пример — список правил:

```bash
ssh root@<host> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/wbrules/Editor/List/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/wbrules/Editor/List/${ID}" -m '"'"'{"id":"'"'"'"$ID"'"'"'","params":{}}'"'"'
  wait $SUB_PID
'
```

## Файловые операции

### Чтение файла с контроллера

```bash
ssh root@<host> cat /etc/wb-mqtt-serial.conf
```

### Запись файла на контроллер

```bash
echo 'содержимое файла' | ssh root@<host> 'cat > /path/to/file'
```

Для многострочного содержимого:

```bash
ssh root@<host> 'cat > /etc/wb-rules/my-rule.js' << 'REMOTEFILE'
defineRule("my-rule", {
  whenChanged: "wb-gpio/A1_OUT",
  then: function(newValue) {
    dev["wb-mr6c_7/K1"] = !!newValue;
  }
});
REMOTEFILE
```

### Скачивание файла с контроллера на локальную машину

```bash
scp root@<host>:/path/to/file ./local-file
```

### Загрузка файла на контроллер

```bash
scp ./local-file root@<host>:/path/to/file
```

### Работа с каталогами

```bash
# Скачать каталог рекурсивно
scp -r root@<host>:/etc/wb-rules ./wb-rules-backup

# Загрузить каталог
scp -r ./configs root@<host>:/mnt/data/
```

## Правила безопасности

### ЗАПРЕЩЕНО

- **НЕ запускать FIT-прошивку** (`wb-fw-update`, `swupdate`, `wb-run-update`, `fit-update`) — прошивка только через web UI контроллера. FIT перезаписывает rootfs целиком, ошибка может окирпичить контроллер.
- **`wb-factoryreset` — только с явным подтверждением пользователя и обязательным бэкапом перед.** Стирает все пользовательские данные (конфиги, правила, шаблоны, Docker-образы), пароль root возвращается к `wirenboard`, кастомные SSH-ключи пропадают. Полный сценарий — в `/controller-update` (Сценарий D). Не запускай по неоднозначной формулировке («очисти», «сброс»).

### Бэкап перед правкой конфигов — ОБЯЗАТЕЛЬНО

Перед изменением любого конфигурационного файла:

```bash
ssh root@<host> 'cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)'
```

Примеры конфигов, которые требуют бэкапа: `wb-mqtt-serial.conf`, `wb-hardware.conf`, файлы в `/etc/network/`, `/etc/mosquitto/`, `/etc/wb-rules/`.

### RPC вместо прямой правки файлов

Для следующих конфигов используй RPC, а не прямую запись:

| Конфиг | RPC-сервис | Почему |
|---|---|---|
| `/etc/wb-mqtt-serial.conf` | `confed/Editor/Save` | Валидация JSON + атомарный рестарт драйвера |
| Правила `/etc/wb-rules/*.js` | `wbrules/Editor/Save` | Валидация JS + горячая перезагрузка |
| `/etc/wb-hardware.conf` | `confed/Editor/Save` | Валидация + применение без reboot |

### Подтверждение пользователя

**Спрашивай подтверждение перед:**
- Деструктивными операциями: `rm`, `reboot`, `dpkg --remove`, `apt-get purge`
- Перезапуском критичных сервисов: `systemctl restart wb-mqtt-serial`, `systemctl restart mosquitto`
- Изменением сетевой конфигурации (можно потерять доступ)
- Остановкой Docker-контейнеров

**БЕЗ подтверждения (выполняй сразу):**
- Диагностика и чтение: `cat`, `journalctl`, `systemctl status`, `mosquitto_sub`, `df`, `ip addr`
- Чтение MQTT-топиков
- Сканирование шины
- Просмотр логов

### Логи — только свежие

После рестарта сервиса смотри только свежие логи, а не весь журнал:

```bash
ssh root@<host> 'journalctl -u wb-mqtt-serial --since "1 min ago" --no-pager'
```

Для длинных журналов:

```bash
ssh root@<host> 'journalctl -u <сервис> -n 50 --no-pager'
```

## Типовые диагностические команды

```bash
# Упавшие сервисы
ssh root@<host> 'systemctl --failed --no-pager'

# Место на диске
ssh root@<host> 'df -h / /mnt/data'

# Нагрузка и память
ssh root@<host> 'uptime; free -h'

# Ошибки в журнале
ssh root@<host> 'journalctl -p err -n 50 --no-pager'

# Kernel mismatch (частая причина проблем после обновления)
ssh root@<host> 'echo "running: $(uname -r)"; dpkg -l linux-image-wb* 2>/dev/null | grep ^ii | awk "{print \"installed:\", \$3}"'

# Список serial-портов
ssh root@<host> 'ls /dev/ttyRS485-* /dev/ttyMOD* 2>/dev/null'

# Проверка MQTT-брокера
ssh root@<host> 'systemctl is-active mosquitto && mosquitto_sub -t "/devices/+/meta/name" -C 5 -W 3'
```

## Скиллы

Доступные скиллы для специфических задач — вызывай `/skill-name` когда задача попадает в их область:

| Скилл | Область |
|---|---|
| `/wb-mqtt-serial` | Конфигурация Modbus-устройств через RPC, включение/отключение каналов, добавление устройств |
| `/serial-templates` | Создание собственных Modbus-шаблонов (когда родного нет) |
| `/wb-rules` | JavaScript-правила автоматизации (defineRule, виртуальные устройства, таймеры, cron) |
| `/scenarios` | Декларативные сценарии Web UI (devicesControl, lightControl, thermostat, schedule) |
| `/notifications` | Telegram/Email/SMS из правил (`Notify.*`), `alarms.conf` |
| `/troubleshooting` | Общая диагностика: упавшие сервисы, место на диске, kernel mismatch, Docker |
| `/troubleshooting-serial` | RS-485/Modbus: CRC-ошибки, таймауты, проблемы сигнала, OWON |
| `/services` | systemd: override-conf, drop-ins, custom units/timers, mask/unmask |
| `/network` | NetworkManager + wb-connection-manager: ethernet/wifi/4G/OpenVPN, failover |
| `/wb-cloud` | Wiren Board Cloud agent: активация, статус, отвязка |
| `/mqtt-broker` | mosquitto admin: пользователи, ACL, мосты, TLS |
| `/controller-backup` | Полный бэкап контроллера: конфиги, пакеты, данные, Docker volumes |
| `/controller-update` | Обновление прошивки и пакетов |
| `/hardware-modules` | Модули расширения (MOD1-MOD4): Zigbee, CAN, RS-485, релейные |
| `/software-install` | Установка ПО: Docker, Zigbee2MQTT, Home Assistant, Node-RED, Grafana |
| `/zigbee` | Zigbee-устройства: сопряжение, управление, группы, OTA |
| `/history` | История данных, графики, экспорт |
| `/diagrams` | Mermaid-диаграммы для визуализации логики |
| `/documentation-search` | Поиск по вики Wiren Board и GitHub-репозиториям |
| `/bugreport` | Составление багрепорта с диагностическим архивом |

## Принципы работы

1. **Сначала диагностика, потом действия.** Прежде чем что-то менять — разберись в текущем состоянии. Прочитай конфиг, проверь логи, посмотри MQTT-топики.

2. **Не угадывай имена топиков — проверь через mosquitto_sub.** Имена устройств и контролов зависят от конфигурации конкретного контроллера. Всегда сначала (формат `topic\tpayload` — TAB-разделитель надёжнее `-v`, имена бывают с пробелами):
   ```bash
   ssh root@<host> "mosquitto_sub -F '%t\\t%p' -t '/devices/+/meta/name' -C 50 -W 3"
   ```

3. **Не спрашивай «хотите ли вы» — делай.** Пользователь остановит если что. Исключение — деструктивные операции (см. правила безопасности выше).

4. **Действуй автономно.** Проверяй факты через SSH, не спрашивай «установлен ли X?» или «какой у вас IP?» — выясни сам:
   ```bash
   ssh root@<host> 'dpkg -l | grep docker'
   ssh root@<host> 'ip addr show'
   ```

5. **Шаблоны и конфиги — с контроллера, не из интернета.** На железке актуальная версия под установленную прошивку. Не скачивай шаблоны с GitHub — используй RPC `device/LoadConfig` или `templates/GetTemplate`.

6. **Документация — перед починкой.** Для типовых задач (Docker, Zigbee, Home Assistant) сначала прочитай соответствующую страницу вики через WebFetch: `https://wiki.wirenboard.com/wiki/<Тема>`.
