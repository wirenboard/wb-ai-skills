---
name: controller-backup
description: "Бэкап и восстановление контроллера Wiren Board через MCP — сбор архива с конфигами, данными и списками пакетов; восстановление после прошивки или на новом контроллере."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# controller-backup (MCP)

Бэкап и восстановление контроллера WB через MCP-tools — собрать архив с конфигами, данными и списками пакетов; отдать пользователю; восстановить после прошивки или на новом контроллере. Подгружай на «сделай бэкап», «бэкап контроллера», «сохрани контроллер», «пришли мне бэкап», «бэкап перед обновлением», «откатить после прошивки», «восстановить из бэкапа», «перенести настройки».

**Это НЕ диагностический архив.** Если пользователь просит «диагностический архив», «логи для поддержки», «wb-diag-collect» — это `/troubleshooting`. Бэкап — полный процесс восстановления контроллера (пакеты, конфиги, данные, RESTORE.md), занимает минуты.

**НА КОНТРОЛЛЕРЕ НЕТ УТИЛИТЫ БЭКАПА.** Не существует `wb-backup`, `wbctl backup`, `backup.sh` — не выдумывай. Бэкап собирается в 3 фазы ниже.

**Бэкап = tar.gz архив** с файлами, конфигами, списками пакетов. Все файлы — в `/mnt/data/ai/wb-ai-integration/backups/`. Не раскидывай по `/tmp`, `/root`, `/mnt/data/backups`.

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Аудит контроллера (пакеты, сервисы, кастомные файлы) | `wb_audit` |
| Слепок состояния для верификации после восстановления | `wb_state_save` |
| Сравнить текущее состояние со слепком | `wb_state_diff` |
| Запустить долгий tar в фоне | `wb_ssh_exec_async` → `wb_job_status` / `wb_job_tail` |
| Прочитать произвольную команду (короткие проверки) | `wb_ssh_exec` |
| Записать RESTORE.md / мелкие файлы | `wb_write_file` |
| Прочитать файл с контроллера (≤64 КБ) | `wb_read_file` |
| Скачать архив на локальный диск | вне MCP — `scp root@<host>:<path> ./` |

## Чеклист — выводи после каждого шага

**БЭКАП НЕ ГОТОВ**, пока не пройдены ВСЕ шаги. После завершения каждого шага выведи чеклист и **немедленно переходи к следующему незавершённому шагу**. Не останавливайся, не спрашивай пользователя — иди до конца и пришли архив.

```
Прогресс бэкапа:
[done] Фаза 1: аудит и отчёт
[...] Фаза 2.1: core-архив (метаданные + конфиги)
[ ] Фаза 2.2: audit-files (кастомные файлы по аудиту)
[ ] Фаза 2.3: Docker volumes (если есть)
[ ] Фаза 3.1: RESTORE.md
[ ] Фаза 3.2: финальная упаковка
[ ] Фаза 3.3: доставка пользователю
```

Пропускай шаги, которые не нужны (напр. Docker volumes если нет Docker), но помечай их `[skip]`. **Не выводи «бэкап готов», пока все шаги не завершены или пропущены.**

## Фаза 1 — аудит и план (первый ответ модели)

### Шаг 1: аудит

`wb_audit sn=<SN>` — возвращает структурированно:
- `fw` — версия прошивки
- `release` — релиз (RELEASE_NAME, SUITE, TARGET)
- `manual` — вручную установленные пакеты
- `installed` — все установленные пакеты
- `enabled` — включённые сервисы
- `units` — кастомные systemd-юниты в `/etc/systemd/system`
- `cron` — задачи cron
- `opt`, `localbin`, `localsbin` — содержимое кастомных каталогов
- `symlinks` — симлинки конфигов WB
- `mntdata` — пользовательские каталоги в `/mnt/data/` с размерами
- `dpkg` — изменённые пакетные файлы (`dpkg --verify`)

### Шаг 1b: слепок состояния

`wb_state_save sn=<SN>` — сохраняет JSON-снимок (ключевые поля: `fwVersion`, `manualPackages`, `enabledUnits`) в `/mnt/data/ai/wb-ai-integration/snapshots/snapshot-<TS>.json` для последующей верификации через `wb_state_diff`.

### Шаг 2: отчёт об отличиях от стока

В сообщении пользователю выведи **отличия от типового контроллера** — это полезный артефакт сам по себе:
- Доустановленные пакеты (`manual` минус стоковые) — список с версиями
- Включённые сервисы сверх стока (`enabled` минус стандартные WB-сервисы)
- Кастомные файлы и скрипты (`opt`, `localbin`, `localsbin`, `units`) — с путями
- Изменённые конфиги (`dpkg` секция) — какие именно
- Пользовательские каталоги в `/mnt/data/` (`mntdata`) — с размерами
- Docker — установлен ли, сколько volumes/контейнеров

Не вываливай сырой вывод — структурируй по человечески. Это первая часть ответа, которую видит пользователь.

### Шаг 3: список путей для архива и сразу запускай фазу 2

По результатам аудита собери **полный список путей** для архива. Источники:

| Поле аудита | Что с ним делать |
|-------------|------------------|
| `opt`, `localbin`, `localsbin` (кастомные файлы) | Добавить каждый путь в список |
| `units` (кастомные systemd-юниты) | Добавить файлы юнитов. Прочитать `ExecStart=` — если скрипт не из пакета, добавить и его |
| `dpkg` (изменённые конфиги) | Добавить каждый изменённый конфиг |
| `mntdata` (пользовательские каталоги) | Это **пользовательские проекты** (не Docker-хранилище!). Добавить каждый каталог, показать размер |
| Доп. пакеты не из стока | `wb_ssh_exec` `dpkg -L <pkg> | grep -E '^/(etc|var/lib|opt|srv)'` — добавить найденные пути |
| Включённые сервисы сверх стока | Не архивировать — они уже в `services-enabled.list` |

**Эвристика по размеру — без подтверждений:**
- Каталог < 100 МБ → включай.
- Каталог 100 МБ - 1 ГБ → включай, но **в сообщении предупреди** «такой-то каталог N МБ — войдёт в архив».
- Каталог > 1 ГБ или named Docker volumes с БД → **пропусти**, перечисли в сообщении как «не вошло в архив, при необходимости запросите отдельно».
- Полный лимит итогового архива ~2 ГБ. Если по эвристике уходит больше — режь сначала самые крупные.

В одном сообщении пользователю: отчёт об отличиях + «включаю в архив: ...; пропускаю как слишком крупное: ...». **Не жди ответа** — сразу переходи к фазе 2.

## Фаза 2 — сборка архива

**Все шаги складывают файлы в один каталог на контроллере.** В фазе 3 весь каталог пакуется в единый архив — объединять вручную не нужно.

### Шаг 1: метаданные и core-конфиги

Запускай через `wb_ssh_exec_async` (фоновая задача). Не пытайся сделать через синхронный `wb_ssh_exec` — таймаут.

```
wb_ssh_exec_async sn=<SN> cmd='set -e; TS=$(date +%Y%m%d-%H%M%S); B=/mnt/data/ai/wb-ai-integration/backups/$TS; mkdir -p $B; cat /etc/wb-fw-version > $B/fw-version 2>/dev/null || true; cp /usr/lib/wb-release $B/wb-release 2>/dev/null || true; apt-mark showmanual > $B/packages-manual.list; dpkg-query -W -f="\${Package}=\${Version}\n" > $B/packages-all.list; systemctl list-unit-files --state=enabled --no-legend | awk "{print \$1}" > $B/services-enabled.list; find /etc -maxdepth 3 -type l -exec sh -c "T=\$(readlink -f \"\$1\"); case \"\$T\" in /mnt/data/*) echo \"\$1 -> \$T\";; esac" _ {} \; > $B/symlinks-etc.list; tar czf $B/core.tar.gz -C / --warning=no-file-changed --ignore-failed-read mnt/data/etc etc/wb-rules etc/wb-mqtt-serial.conf etc/wb-mqtt-serial.conf.d etc/network etc/hostname etc/resolv.conf etc/ntp.conf etc/chrony 2>/dev/null || true; find / /mnt/data -xdev \( -path /mnt/data/.docker -o -path /mnt/data/var/lib/containerd \) -prune -o \( -name "docker-compose.y*ml" -o -name "compose.y*ml" \) -print 2>/dev/null | tar czf $B/compose-files.tar.gz -T - 2>/dev/null || true; SNAP=$(ls -t /mnt/data/ai/wb-ai-integration/snapshots/snapshot-*.json 2>/dev/null | head -1); [ -n "$SNAP" ] && cp "$SNAP" $B/state-snapshot.json; echo BACKUP_DIR=$B; du -sh $B $B/*'
```

`wb_job_tail job_id=<id>` — следи за прогрессом. Из итогового вывода возьми `BACKUP_DIR=...` (например `/mnt/data/ai/wb-ai-integration/backups/20260419-224500`). **Подставляй этот конкретный путь во все последующие шаги** — переменная `$B` в новых вызовах не сохраняется.

### Шаг 2: данные по результатам аудита

```
wb_ssh_exec_async sn=<SN> cmd='tar czf <BACKUP_DIR>/audit-files.tar.gz --warning=no-file-changed --ignore-failed-read <пути из аудита> 2>/dev/null || true; du -sh <BACKUP_DIR>/audit-files.tar.gz'
```

Подставляй **конкретные пути** из шага 3 фазы 1:
- Кастомные файлы: `/opt/my-app/`, `/usr/local/bin/my-script.sh`
- Кастомные systemd-юниты: `/etc/systemd/system/my-service.service`
- Изменённые конфиги: `/etc/mosquitto/mosquitto.conf`
- Пользовательские каталоги: `/mnt/data/picoclow-docker/` — это пользовательские проекты, бэкапить!
- Конфиги доп. пакетов: пути из `dpkg -L`
- Конфиги известных пакетов (таблица ниже): `/mnt/data/root/zigbee2mqtt`, `/etc/mosquitto`, `/etc/nginx`, `/var/lib/grafana/grafana.db`, `/etc/influxdb`, `/root/.node-red/flows*.json`, `/root/.node-red/settings.js`, `/mnt/data/etc/docker`, `/etc/cron.d`

### Шаг 3: named Docker volumes (если есть Docker)

Если в доп. пакетах есть `docker-ce`:

```
wb_ssh_exec sn=<SN> cmd='docker volume ls -q 2>/dev/null'
```

Если есть volumes с данными:

```
wb_ssh_exec_async sn=<SN> cmd='for v in $(docker volume ls -q); do docker run --rm -v $v:/data alpine tar czf - /data > <BACKUP_DIR>/docker-volume-$v.tar.gz 2>/dev/null; done; ls -lh <BACKUP_DIR>/docker-volume-*.tar.gz 2>/dev/null'
```

## Фаза 3 — доставка (после завершения ВСЕХ задач)

Дождись завершения всех шагов фазы 2 (`wb_job_status` → `exited`).

### 1. RESTORE.md

`wb_write_file sn=<SN> path=<BACKUP_DIR>/RESTORE.md content=<инструкция>`. Содержимое — по фактическим данным аудита. **Обязательные** секции (не пропускай ни одну):

1. **Пакеты** — перечисли ВСЕ доп. пакеты из аудита. Для Docker — через `wb-docker-manager.sh`. Для остальных — `apt install <pkg1> <pkg2> ...`. Порядок: сначала зависимости, потом зависимые. **Эта секция критична** — без пакетов конфиги бесполезны.
2. **Файлы** — что распаковать и куда (`tar xzf core.tar.gz -C /`, `tar xzf audit-files.tar.gz -C /`).
3. **Симлинки** — какие восстановить (из `symlinks-etc.list`).
4. **Сервисы** — какие включить (`systemctl enable ...`) — по списку доп. включённых сервисов из аудита.
5. **Ручные шаги** — что нельзя автоматизировать (Docker-образы: `docker compose pull`, БД, node_modules).
6. **Верификация** — `wb_state_diff` против `state-snapshot.json`.

Пиши конкретные пути, имена пакетов и команды — не `$переменные` и не `<placeholder>`.

### 2. Собери в один файл

```
wb_ssh_exec_async sn=<SN> cmd='cd /mnt/data/ai/wb-ai-integration/backups && tar czf backup-<TS>.tar.gz <TS>/ && du -sh backup-<TS>.tar.gz'
```

### 3. Проверь размер и отдай

```
wb_ssh_exec sn=<SN> cmd='stat -c%s /mnt/data/ai/wb-ai-integration/backups/backup-<TS>.tar.gz'
```

- < 200 МБ → пользователь скачивает локально:
  ```bash
  scp root@wirenboard-<SN>.local:/mnt/data/ai/wb-ai-integration/backups/backup-<TS>.tar.gz ./
  ```
- > 200 МБ → предложи пользователю скопировать самостоятельно через `scp` (через MCP не тяни — `wb_read_file` лимитирован 64 КБ).

### 4. Итоговый отчёт

- Какие доп. пакеты нужно установить при восстановлении — перечисли конкретные имена.
- Что сохранено (конкретные пути).
- Что НЕ сохранено — предупреди:
  - `/mnt/data/.docker/` (внутреннее хранилище Docker daemon: образы, слои) — восстанавливаются через `docker pull` / `docker compose pull`.
  - Большие БД (InfluxDB) — `influxd backup` вручную.
  - Node-RED `node_modules` — восстановится через `npm install`.

## Docker: что бэкапить, что нет

**НЕ путай пользовательские проекты с Docker-хранилищем!**

| Что | Где | Бэкапить? | Как |
|-----|-----|-----------|-----|
| compose-файлы | в проектах (`/mnt/data/<проект>/`) | ДА | tar как есть |
| bind-mount данные | в проектах | ДА | tar как есть |
| named volumes | `docker volume ls` | ДА, если есть данные | `docker run --rm -v vol:/d alpine tar czf - /d > vol.tar.gz` |
| Docker daemon (`/mnt/data/.docker/`) | внутреннее хранилище | НЕТ | образы через `docker pull`, восстановятся из compose |
| Конфиг демона | `/mnt/data/etc/docker/` | ДА | уже в core-архиве |

Пример: `/mnt/data/picoclow-docker/` (82 МБ) — это **проект пользователя** с compose, конфигами и данными. Его НАДО бэкапить целиком. А `/mnt/data/.docker/` — это слои образов, их бэкапить бессмысленно.

## Известные пакеты — что в архиве, что предупредить

| Пакет | Что в архиве | Что предупредить |
|-------|--------------|------------------|
| `docker-ce` | `/mnt/data/etc/docker/`, compose-файлы, проекты из `mntdata` | `/mnt/data/.docker/` НЕ в архиве. Docker ставится через `wb-docker-manager.sh`. Named volumes — отдельно |
| `zigbee2mqtt` | `/mnt/data/root/zigbee2mqtt/` | -- |
| `nodered` | `flows*.json`, `settings.js` | `node_modules` восстановится через `npm install` |
| `mosquitto` | `/etc/mosquitto/` | -- |
| `influxdb` | `/etc/influxdb/` | БД через `influxd backup`, не tar |
| `grafana` | `/var/lib/grafana/grafana.db`, `/etc/grafana/` | -- |
| `nginx` | `/etc/nginx/` | Сертификаты `/etc/letsencrypt/` — отдельно |

## Что переживает FIT, что нет

FIT перезаписывает rootfs, НЕ трогает `/mnt/data/`.

| Переживает | Стирается |
|------------|-----------|
| `/mnt/data/` целиком | `/usr/local/bin/`, `/opt/`, `/srv/` |
| Конфиги с симлинком в `/mnt/data/etc/` | `/etc/cron.d/<кастом>`, `/etc/systemd/system/<кастом>` |
| Сеть/время из веб-интерфейса | apt-пакеты вне стока |

## Восстановление

1. Найди бэкап: `wb_ssh_exec` `ls -lt /mnt/data/ai/wb-ai-integration/backups/`. Бэкап переживает FIT. Или пользователь загружает файл локальным `scp ./backup-<TS>.tar.gz root@wirenboard-<SN>.local:/mnt/data/ai/wb-ai-integration/backups/`.
2. Прочитай RESTORE.md: `wb_read_file sn=<SN> path=/mnt/data/ai/wb-ai-integration/backups/<TS>/RESTORE.md`.
3. Выполняй по шагам с подтверждением пользователя. Пакеты — через `wb_ssh_exec_async`.
4. Верификация: `wb_state_diff sn=<SN> snapshot=<BACKUP_DIR>/state-snapshot.json` — что отличается от состояния «до».

## Грабли

- Выдумывать `wb-backup`, `wbctl backup`, `backup.sh` — их не существует.
- Core-скрипт менять нельзя. А вот audit-tar (шаг 2 фазы 2) — обязательно строй по данным аудита, не пропускай находки.
- Остановиться на слепке — это НЕ бэкап. Продолжай к фазе 2.
- Запускать tar через синхронный `wb_ssh_exec` — таймаут. Только `wb_ssh_exec_async`.
- Бэкапить `/etc` или `/mnt/data` целиком — огромно и бесполезно.
- Молчать про `/mnt/data/.docker/` — предупреди, что не в архиве.
- Лить сырой вывод аудита — покажи отчёт по категориям.
- Раскидывать файлы по `/tmp`, `/root`, `/mnt/data/backups` — всё в `/mnt/data/ai/wb-ai-integration/backups/`.
- Пропустить изменённые конфиги или кастомные systemd-юниты — они тоже нужны в архиве.

## Документация

- FIT-update: <https://wirenboard.com/wiki/Wirenboard_Firmware_Update>
- Раздел data: <https://wirenboard.com/wiki/Data_Partition>
