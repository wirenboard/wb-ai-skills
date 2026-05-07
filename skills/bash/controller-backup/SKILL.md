---
name: controller-backup
description: "Бэкап и восстановление контроллера Wiren Board — сбор архива с конфигами, данными и списками пакетов; восстановление после прошивки или на новом контроллере."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# controller-backup

Бэкап и восстановление контроллера WB — собрать архив с конфигами, данными и списками пакетов; отдать пользователю; восстановить после прошивки или на новом контроллере. Подгружай на «сделай бэкап», «бэкап контроллера», «сохрани контроллер», «пришли мне бэкап», «бэкап перед обновлением», «откатить после прошивки», «восстановить из бэкапа», «перенести настройки».

**Это НЕ диагностический архив.** Если пользователь просит «диагностический архив», «логи для поддержки», «wb-diag-collect» — это скилл `troubleshooting`, не бэкап. Бэкап — полный процесс восстановления контроллера (пакеты, конфиги, данные, RESTORE.md), занимает минуты.

**НА КОНТРОЛЛЕРЕ НЕТ УТИЛИТЫ БЭКАПА.** Не существует `wb-backup`, `wbctl backup`, `backup.sh` — не выдумывай. Бэкап собирается в 3 фазы ниже.

**Бэкап = tar.gz архив** с файлами, конфигами, списками пакетов.

**Все файлы — в `/mnt/data/ai/wb-ai-integration/backups/`.** Не раскидывай по `/tmp`, `/root`, `/mnt/data/backups`.

**Переменная HOST:** во всех примерах ниже `<HOST>` означает `wirenboard-<SN>.local`, где `<SN>` — серийный номер контроллера (например `wirenboard-AABBCCDD.local`). Подставляй реальный адрес.

## Чеклист — выводи после каждого шага

**БЭКАП НЕ ГОТОВ**, пока не пройдены ВСЕ шаги. После завершения каждого шага выведи чеклист и **немедленно переходи к следующему незавершённому шагу**. Не останавливайся, не спрашивай пользователя — иди до конца и пришли архив.

```
Прогресс бэкапа:
[done] Фаза 1.0: аудит и отчёт
[ ] Фаза 1b: state-snapshot (для верификации после восстановления)
[ ] Фаза 2.1: core-архив (метаданные + конфиги)
[ ] Фаза 2.2: audit-files (кастомные файлы по аудиту)
[ ] Фаза 2.3: Docker volumes (если есть)
[ ] Фаза 3.1: RESTORE.md
[ ] Фаза 3.2: финальная упаковка
[ ] Фаза 3.3: доставка пользователю
```

Пропускай шаги которые не нужны (напр. Docker volumes если нет Docker), но помечай их `[skip]`. **Не выводи «бэкап готов» пока все шаги не завершены или пропущены.**

## Фаза 1 — аудит и план (первый ответ модели)

### Шаг 1: собери данные — аудит контроллера

Аудит выполняется одним SSH-скриптом, который собирает все данные о состоянии контроллера:

```bash
ssh root@<HOST> 'echo "===WB-AUDIT===fw"; cat /etc/wb-fw-version 2>/dev/null || true; echo "===WB-AUDIT===release"; cat /usr/lib/wb-release 2>/dev/null || true; echo "===WB-AUDIT===manual"; apt-mark showmanual 2>/dev/null | sort; echo "===WB-AUDIT===installed"; dpkg-query -W -f="\${Package}\n" 2>/dev/null | sort; echo "===WB-AUDIT===enabled"; systemctl list-unit-files --state=enabled --no-legend 2>/dev/null | awk "{print \$1}" | sort; echo "===WB-AUDIT===units"; find /etc/systemd/system -maxdepth 2 -name "*.service" -type f 2>/dev/null | sort; echo "===WB-AUDIT===cron"; for d in /etc/cron.d /etc/cron.hourly /etc/cron.daily /etc/cron.weekly /var/spool/cron/crontabs; do ls -A "$d" 2>/dev/null | grep -v "^\.placeholder$" | sed "s|^|$d/|"; done; echo "===WB-AUDIT===opt"; ls -A /opt 2>/dev/null; echo "===WB-AUDIT===localbin"; ls -A /usr/local/bin 2>/dev/null; echo "===WB-AUDIT===localsbin"; ls -A /usr/local/sbin 2>/dev/null; echo "===WB-AUDIT===symlinks"; for p in /etc/wb-rules /etc/wb-rules-modules /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.d; do echo "$p|$(readlink -f $p 2>/dev/null)"; done; echo "===WB-AUDIT===mntdata"; shopt -s nullglob dotglob; for d in /mnt/data/*/; do case "$(basename "$d")" in etc|var|root|snapshots|backups|uploads|.docker|ai|.wb-restore|.wb-update|lost+found) continue;; *) du -sh "$d" 2>/dev/null;; esac; done; shopt -u dotglob; echo "===WB-AUDIT===dpkg"; dpkg --verify 2>/dev/null | grep -v -E "/usr/share/(doc|locale|man|lintian|gtk-doc|gnome|info|help)"; echo "===WB-AUDIT===end"'
```

Разбор секций вывода:
- `fw` — версия прошивки
- `release` — релиз (RELEASE_NAME, SUITE, TARGET)
- `manual` — вручную установленные пакеты
- `installed` — все установленные пакеты
- `enabled` — включённые сервисы
- `units` — кастомные systemd-юниты в `/etc/systemd/system`
- `cron` — задачи cron
- `opt` — содержимое `/opt`
- `localbin` — содержимое `/usr/local/bin`
- `localsbin` — содержимое `/usr/local/sbin`
- `symlinks` — симлинки конфигов WB
- `mntdata` — пользовательские каталоги в `/mnt/data/` с размерами
- `dpkg` — изменённые пакетные файлы (dpkg --verify)

### Шаг 1b: слепок для верификации после восстановления

Сохрани слепок состояния контроллера в JSON на контроллере:

```bash
ssh root@<HOST> 'mkdir -p /mnt/data/ai/wb-ai-integration/snapshots'
```

Соберите те же данные из аудита и сформируйте JSON-файл:

```bash
ssh root@<HOST> 'cat > /mnt/data/ai/wb-ai-integration/snapshots/snapshot-$(date +%Y-%m-%dT%H-%M-%S).json << SNAPEOF
{
  "_comment": "Слепок контроллера для верификации бэкапа",
  "takenAt": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
  "fwVersion": "'"$(cat /etc/wb-fw-version 2>/dev/null)"'",
  "manualPackages": '"$(apt-mark showmanual 2>/dev/null | sort | jq -Rsc 'split("\n") | map(select(. != ""))')"',
  "enabledUnits": '"$(systemctl list-unit-files --state=enabled --no-legend 2>/dev/null | awk "{print \$1}" | sort | jq -Rsc 'split("\n") | map(select(. != ""))')"'
}
SNAPEOF
echo "Snapshot saved: $(ls -t /mnt/data/ai/wb-ai-integration/snapshots/snapshot-*.json 2>/dev/null | head -1)"'
```

Примечание: если `jq` нет на контроллере, формируй JSON другим способом или пропусти этот шаг — он не критичен для бэкапа.

### Шаг 2: отчёт об отличиях от стока

В сообщении пользователю выведи **отличия от типового контроллера** — это полезный артефакт сам по себе:
- Доустановленные пакеты (`manual` минус стоковые) — список с версиями
- Включённые сервисы сверх стока (`enabled` минус стандартные WB-сервисы)
- Кастомные файлы и скрипты (`opt`, `localbin`, `localsbin`, `units`) — с путями
- Изменённые конфиги (`dpkg` секция) — какие именно
- Пользовательские каталоги в `/mnt/data/` (`mntdata`) — с размерами
- Docker — установлен ли, сколько volumes/контейнеров

Не вываливай сырой вывод — структурируй по человечески. Это первая часть ответа, которую видит пользователь.

### Шаг 3: составь список путей и сразу запускай фазу 2

По результатам аудита собери **полный список путей** для архива. Источники:

| Поле аудита | Что с ним делать |
|---|---|
| `opt`, `localbin`, `localsbin` (кастомные файлы) | Добавить каждый путь в список |
| `units` (кастомные systemd-юниты) | Добавить файлы юнитов. Прочитать `ExecStart=` — если скрипт не из пакета, добавить и его |
| `dpkg` (изменённые конфиги) | Добавить каждый изменённый конфиг |
| `mntdata` (пользовательские каталоги) | Это **пользовательские проекты** (не Docker-хранилище!). Добавить каждый каталог, показать размер |
| Доп. пакеты не из стока | `ssh root@<HOST> "dpkg -L <pkg> | grep -E '^/(etc|var/lib|opt|srv)'"` — добавить найденные пути |
| Включённые сервисы сверх стока | Не архивировать — запишется в `services-enabled.list` автоматически |

**Эвристика по размеру — без подтверждений:**
- Каталог < 100 МБ -> включай.
- Каталог 100 МБ - 1 ГБ -> включай, но **в сообщении предупреди** «такой-то каталог N МБ — войдёт в архив».
- Каталог > 1 ГБ или named Docker volumes с БД -> **пропусти**, перечисли в сообщении как «не вошло в архив, при необходимости запросите отдельно».
- Полный лимит итогового архива ~2 ГБ. Если по эвристике уходит больше — режь сначала самые крупные.

В одном сообщении пользователю: отчёт об отличиях + «включаю в архив: ...; пропускаю как слишком крупное: ...». **Не жди ответа** — сразу переходи к фазе 2.

## Фаза 2 — сборка архива

**Все шаги складывают файлы в один каталог на контроллере.** В фазе 3 весь каталог пакуется в единый архив — объединять вручную не нужно.

> Замечание: core-tar включает `mnt/data/etc` рекурсивно — поэтому `/mnt/data/etc/docker/`, `/mnt/data/etc/wb-mqtt-serial.conf` (через симлинк) и пр. **уже там**. Не дублируй их в audit-files-tar.

### Шаг 1: метаданные и core-конфиги

Запускай ЭТОТ скрипт через systemd-run (фоновая задача). Не придумывай свой скрипт для этой части.

```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-job-$(cat /dev/urandom | tr -dc a-z0-9 | head -c8) --collect bash -c "set -e; TS=\$(date +%Y%m%d-%H%M%S); B=/mnt/data/ai/wb-ai-integration/backups/\$TS; mkdir -p \$B; cat /etc/wb-fw-version > \$B/fw-version 2>/dev/null || true; cp /usr/lib/wb-release \$B/wb-release 2>/dev/null || true; apt-mark showmanual > \$B/packages-manual.list; dpkg-query -W -f='"'"'\${Package}=\${Version}\n'"'"' > \$B/packages-all.list; systemctl list-unit-files --state=enabled --no-legend | awk '"'"'{print \$1}'"'"' > \$B/services-enabled.list; find /etc -maxdepth 3 -type l -exec sh -c '"'"'T=\$(readlink -f \"\$1\"); case \"\$T\" in /mnt/data/*) echo \"\$1 -> \$T\";; esac'"'"' _ {} \\; > \$B/symlinks-etc.list; tar czf \$B/core.tar.gz -C / --warning=no-file-changed --ignore-failed-read mnt/data/etc etc/wb-rules etc/wb-mqtt-serial.conf etc/wb-mqtt-serial.conf.d etc/network etc/hostname etc/resolv.conf etc/ntp.conf etc/chrony 2>/dev/null || true; find / /mnt/data -xdev \\( -path /mnt/data/.docker -o -path /mnt/data/var/lib/containerd \\) -prune -o \\( -name '"'"'docker-compose.y*ml'"'"' -o -name '"'"'compose.y*ml'"'"' \\) -print 2>/dev/null | tar czf \$B/compose-files.tar.gz -T - 2>/dev/null || true; SNAP=\$(ls -t /mnt/data/ai/wb-ai-integration/snapshots/snapshot-*.json 2>/dev/null | head -1); [ -n \"\$SNAP\" ] && cp \"\$SNAP\" \$B/state-snapshot.json; echo BACKUP_DIR=\$B; du -sh \$B \$B/*"'
```

Проверь статус задачи:
```bash
ssh root@<HOST> "systemctl status wb-ai-job-* --no-pager 2>/dev/null | head -30"
```

Из вывода джобы возьми путь `BACKUP_DIR=...` — например `/mnt/data/ai/wb-ai-integration/backups/20260419-224500`. **Подставляй этот конкретный путь во все последующие шаги.** Не пиши `$B` в следующих командах — переменная не сохраняется между вызовами!

Чтобы узнать лог фоновой задачи:
```bash
ssh root@<HOST> "journalctl -u 'wb-ai-job-*' --since '5 minutes ago' --no-pager | tail -20"
```

### Шаг 2: данные по результатам аудита

```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-job-$(cat /dev/urandom | tr -dc a-z0-9 | head -c8) --collect bash -c "tar czf <BACKUP_DIR>/audit-files.tar.gz --warning=no-file-changed --ignore-failed-read <пути из аудита> 2>/dev/null || true; du -sh <BACKUP_DIR>/audit-files.tar.gz"'
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
```bash
ssh root@<HOST> "docker volume ls -q 2>/dev/null"
```
Если есть volumes с данными:
```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-job-$(cat /dev/urandom | tr -dc a-z0-9 | head -c8) --collect bash -c "for v in \$(docker volume ls -q); do docker run --rm -v \$v:/data alpine tar czf - /data > <BACKUP_DIR>/docker-volume-\$v.tar.gz 2>/dev/null; done; ls -lh <BACKUP_DIR>/docker-volume-*.tar.gz 2>/dev/null"'
```

## Фаза 3 — доставка (после завершения ВСЕХ задач)

Дождись завершения всех шагов фазы 2 (core + audit-files + docker volumes если были).

### 1. RESTORE.md

Сгенерируй и запиши инструкцию восстановления:
```bash
echo '<содержимое RESTORE.md>' | ssh root@<HOST> 'cat > <BACKUP_DIR>/RESTORE.md'
```

Содержимое — по фактическим данным аудита. **Обязательные** секции (не пропускай ни одну):

1. **Пакеты** — перечисли ВСЕ доп. пакеты из аудита. Для Docker — через `wb-docker-manager.sh`. Для остальных — `apt install <pkg1> <pkg2> ...`. Порядок: сначала зависимости, потом зависимые. **Эта секция критична** — без пакетов конфиги бесполезны.
2. **Файлы** — что распаковать и куда (`tar xzf core.tar.gz -C /`, `tar xzf audit-files.tar.gz -C /`)
3. **Симлинки** — какие восстановить (из `symlinks-etc.list`)
4. **Сервисы** — какие включить (`systemctl enable ...`) — по списку доп. включённых сервисов из аудита
5. **Ручные шаги** — что нельзя автоматизировать (Docker-образы: `docker compose pull`, БД, node_modules)
6. **Верификация** — сравнить текущее состояние с `state-snapshot.json`

Пиши конкретные пути, имена пакетов и команды — не `$переменные` и не `<placeholder>`.

### 2. Собери в один файл

```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-job-$(cat /dev/urandom | tr -dc a-z0-9 | head -c8) --collect bash -c "cd /mnt/data/ai/wb-ai-integration/backups && tar czf backup-<TS>.tar.gz <TS>/ && du -sh backup-<TS>.tar.gz"'
```

### 3. Проверь размер и отдай

```bash
ssh root@<HOST> "stat -c%s /mnt/data/ai/wb-ai-integration/backups/backup-<TS>.tar.gz"
```
- < 200 МБ -> скачай:
  ```bash
  scp root@<HOST>:/mnt/data/ai/wb-ai-integration/backups/backup-<TS>.tar.gz ./
  ```
- > 200 МБ -> предложи пользователю скопировать самостоятельно через scp

### 4. Итоговый отчёт

- Какие доп. пакеты нужно установить при восстановлении — перечисли конкретные имена
- Что сохранено (конкретные пути)
- Что НЕ сохранено — предупреди:
  - `/mnt/data/.docker/` (внутреннее хранилище Docker daemon: образы, слои) — восстанавливаются через `docker pull` / `docker compose pull`
  - Большие БД (InfluxDB) — `influxd backup` вручную
  - Node-RED `node_modules` — восстановится через `npm install`

## Docker: что бэкапить, что нет

**НЕ путай пользовательские проекты с Docker-хранилищем!**

| Что | Где | Бэкапить? | Как |
|---|---|---|---|
| compose-файлы | в проектах (`/mnt/data/<проект>/`) | ДА | tar как есть |
| bind-mount данные | в проектах | ДА | tar как есть |
| named volumes | `docker volume ls` | ДА, если есть данные | `docker run --rm -v vol:/d alpine tar czf - /d > vol.tar.gz` |
| Docker daemon (`/mnt/data/.docker/`) | внутреннее хранилище | НЕТ | образы через `docker pull`, восстановятся из compose |
| Конфиг демона | `/mnt/data/etc/docker/` | ДА | уже в core-архиве |

Пример: `/mnt/data/picoclow-docker/` (82 МБ) — это **проект пользователя** с compose, конфигами и данными. Его НАДО бэкапить целиком. А `/mnt/data/.docker/` — это слои образов, их бэкапить бессмысленно.

## Известные пакеты — что в архиве, что предупредить

| Пакет | Что в архиве | Что предупредить |
|---|---|---|
| `docker-ce` | `/mnt/data/etc/docker/` (попадает рекурсивно через `mnt/data/etc` в core-tar), compose-файлы, проекты из `mntdata` | `/mnt/data/.docker/` НЕ в архиве. Docker ставится **либо** через `wb-docker-manager.sh` из community-репо (если он есть на свежем контроллере: `wget -O /tmp/wb-docker-manager.sh https://raw.githubusercontent.com/wirenboard/wb-community/refs/heads/main/scripts/docker-install/wb-docker-manager.sh && bash /tmp/wb-docker-manager.sh --install`), **либо** обычным `apt install docker-ce containerd.io docker-ce-cli` если по версии `dpkg-query` видно, что было установлено именно так. Named volumes — отдельно через `docker run -v ...` |
| `zigbee2mqtt` | `/mnt/data/root/zigbee2mqtt/` | -- |
| `nodered` | `flows*.json`, `settings.js` | `node_modules` восстановится через `npm install` |
| `mosquitto` | `/etc/mosquitto/` | -- |
| `influxdb` | `/etc/influxdb/` | БД через `influxd backup`, не tar |
| `grafana` | `/var/lib/grafana/grafana.db`, `/etc/grafana/` | -- |
| `nginx` | `/etc/nginx/` | Сертификаты `/etc/letsencrypt/` — отдельно |

## Что переживает FIT, что нет

FIT перезаписывает rootfs, НЕ трогает `/mnt/data/`.

| Переживает | Стирается |
|---|---|
| `/mnt/data/` целиком | `/usr/local/bin/`, `/opt/`, `/srv/` |
| Конфиги с симлинком в `/mnt/data/etc/` | `/etc/cron.d/<кастом>`, `/etc/systemd/system/<кастом>` |
| Сеть/время из веб-интерфейса | apt-пакеты вне стока |

## Восстановление

1. Найди бэкап:
   ```bash
   ssh root@<HOST> "ls -lt /mnt/data/ai/wb-ai-integration/backups/"
   ```
   Бэкап переживает FIT. Или пользователь загружает файл:
   ```bash
   scp ./backup-<TS>.tar.gz root@<HOST>:/mnt/data/ai/wb-ai-integration/backups/
   ```
2. Прочитай RESTORE.md:
   ```bash
   ssh root@<HOST> "cat /mnt/data/ai/wb-ai-integration/backups/<TS>/RESTORE.md"
   ```
3. Выполняй по шагам с подтверждением пользователя. Пакеты — через systemd-run.
4. Верификация: сравни текущее состояние с `state-snapshot.json`.

## Грабли

- Выдумывать `wb-backup`, `wbctl backup`, `backup.sh` — их не существует.
- Core-скрипт менять нельзя. А вот audit-tar (шаг 2 фазы 2) — обязательно строй по данным аудита, не пропускай находки.
- Остановиться на слепке — это НЕ бэкап. Продолжай к фазе 2.
- Запускать tar в обычном ssh — таймаут. Только через systemd-run.
- Бэкапить `/etc` или `/mnt/data` целиком — огромно и бесполезно.
- Молчать про `/mnt/data/.docker/` — предупреди что не в архиве.
- Лить сырой вывод аудита — покажи отчёт по категориям.
- Раскидывать файлы по `/tmp`, `/root`, `/mnt/data/backups` — всё в `/mnt/data/ai/wb-ai-integration/backups/`.
- Пропустить изменённые конфиги или кастомные systemd-юниты — они тоже нужны в архиве.

## Документация

- FIT-update: <https://wirenboard.com/wiki/Wirenboard_Firmware_Update>
- Раздел data: <https://wirenboard.com/wiki/Data_Partition>
