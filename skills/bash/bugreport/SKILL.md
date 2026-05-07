---
name: bugreport
description: Составление багрепорта для поддержки Wiren Board — сбор данных, диагархив, оформление.
allowed-tools: Bash Read Write WebFetch
---

# bugreport

Составление багрепорта для службы поддержки Wiren Board.

## Принцип

Максимум собери сам через скиллы `/troubleshooting`, `/troubleshooting-serial`, `/wiren-board` и mDNS-прогрев из мастера; минимум спрашивай. Список в шаге 4 — **запасной вариант** для случаев, когда автодиагностика не дала ответа на конкретный пункт.

**Перед изменением чего-либо** на продакшн-контроллере для проверки гипотезы — `/controller-backup` (короткий снапшот через шаг 1b).

## Порядок

### 1. Собери паспорт контроллера

Снимок состояния (один SSH-вызов, сохрани вывод в файл — пригодится в шаблоне):

```bash
ssh root@<HOST> 'echo "=== HW ==="; cat /var/lib/wirenboard/short_sn.conf 2>/dev/null; cat /usr/lib/wb-release 2>/dev/null; echo "Kernel: $(uname -r)"; echo "FW: $(cat /etc/wb-fw-version 2>/dev/null)"; echo "Uptime:"; uptime; echo "=== DISK ==="; df -h / /mnt/data; echo "=== FAILED ==="; systemctl --failed --no-pager; echo "=== ERRORS (last hour) ==="; journalctl -p err --since "1 hour ago" --no-pager' | tee /tmp/wb-snapshot-<SN>-$(date +%Y%m%d).txt
```

Для конкретного упавшего сервиса:
```bash
ssh root@<HOST> "systemctl status <unit> --no-pager; journalctl -u <unit> --since '1 day ago' --no-pager"
```

Kernel mismatch (частая причина проблем после обновления — см. `/troubleshooting`):
```bash
ssh root@<HOST> 'echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" 2>/dev/null | grep ^ii'
```

### 2. Собери диагностический архив

`wb-diag-collect <prefix>` принимает **префикс имени файла**, не директорию. Реальный файл попадает в **родительский каталог префикса** под именем `<prefix>_<SN>_<TS>.zip`.

```bash
# Собрать (фоновая задача, ~30-60 сек):
ssh root@<HOST> 'mkdir -p /mnt/data/ai/wb-ai-integration && systemd-run --unit=wb-ai-diag --collect bash -c "wb-diag-collect /mnt/data/ai/wb-ai-integration/diag"'

# Дождись завершения и узнай реальное имя последнего архива:
LATEST=$(ssh root@<HOST> 'ls -t /mnt/data/ai/wb-ai-integration/diag_*.zip 2>/dev/null | head -1')
echo "diag-архив: $LATEST"

# Скачай **только последний** под понятным именем:
scp root@<HOST>:"$LATEST" "/tmp/$(basename $LATEST .zip)-bugreport.zip"
```

Без `LATEST` глоб `diag*.zip` развернётся на удалённой стороне и скачает **все** старые архивы — на A25NDEMJ их обычно 5-6 штук.

**Что покрывает diag-архив:**
- `last_logs.log` / `last_logs.previous-boot.log` — журнал текущего и предыдущего boot целиком.
- `dmesg.log` / `dmesg.previous-boot.log` — kernel ring buffer.
- `service/<unit>.service.log` — журнал по каждому **WB-сервису** (mosquitto, wb-mqtt-*, wb-rules, wb-device-manager, wb-cloud-agent и т.п.).
- `etc/`, `usr/lib/`, `static/` — конфиги, версии, описание ревизии.
- `dpkg_l.log`, `df_h.log`, `free.log`, `ps_aux.log`, `nmcli.log`, `dmesg`-ы, NetworkManager-конфиги, eMMC EXT_CSD.

**Чего НЕТ в архиве** (нужно собирать отдельно и приложить к багрепорту):
- Не-WB systemd-юниты (`fstrim.service`, `apt-daily.service`, кастомные `*.service`) — их журналов в архиве нет.
- Логи Docker-контейнеров (`nodered`, `zigbee2mqtt`-в-Docker и т.п.).
- Долгопериодные выборки по приоритету (за неделю/месяц) — в `last_logs` только текущий boot.
- Снимки MQTT-состояния (`mosquitto_sub /devices/+/meta/name`, `bridge/state`).

**Прицельный сбор того, чего нет в архиве:**
```bash
# Журнал упавшего не-WB юнита целиком (укажи `-u <unit>`):
ssh root@<HOST> "journalctl -u <unit> --no-pager --since '1 month ago'" > /tmp/<unit>.log

# Логи Docker-контейнера (для багрепортов про nodered/Z2M-в-Docker):
ssh root@<HOST> "docker logs --tail 1000 --timestamps <container>" 2>&1 > /tmp/<container>.log

# Все ошибки за неделю с фильтром:
ssh root@<HOST> "journalctl -p err --since '7 days ago' --no-pager" > /tmp/errors-7d.log

# Снимок состояния MQTT (для багов про устройства):
ssh root@<HOST> "mosquitto_sub -F '%t\t%p' -t '/devices/+/meta/name' -W 5" > /tmp/mqtt-devices.txt
```

В багрепорт прикладывай **архив + дополнительно собранные логи** под понятными именами, чтобы поддержка не искала.

**Когда архив не нужен:** для упавшего systemd-юнита часто достаточно `journalctl -u <unit> --no-pager` + `systemctl status <unit>` + `systemctl cat <unit>` (например, наш кейс с `fstrim.service`). Архив на сотни КБ — нагрузка на eMMC; собирай если поддержка попросит, или если причина не локализована за 5 минут шагом 1.

### 3. Опиши проблему

Из контекста диалога ты уже знаешь, что произошло. Опиши сам, не переспрашивая.

### 4. Спроси только то, что **нельзя** узнать с контроллера

Этот список — запасной, для пунктов, которые не удалось выяснить шагом 1. Сначала проверь сам через скиллы (`/wiren-board`, `/troubleshooting`).

- **Severity** и контекст: продакшн или стенд, влияет ли на пользователей сейчас.
- **Физическое подключение** (если проблема с оборудованием — фото шины, схема, тип блока питания).
- **Что видит в браузере/на экране** (если проблема UI — скриншот).
- **Воспроизводимость** — если в логах не видно по таймштампам.
- **Что уже пробовали** для обхода (часто пользователь молчит про это; явно спроси).
- **Желательный исход**: фикс в пакете / временный обход / можно ли вечером перезагрузить.
- **Куда вернётся ответ**: тикет в support@wirenboard.com / форум / телеграм-чат.

Спрашивай одним списком, не по одному вопросу.

### 5. Оформи багрепорт

Шаблон:

```
**Тема:** <SN> — <короткий симптом одной строкой>

1. **Оборудование** — SN, релиз (`wb-XXXX`/target), ядро, fw, версии релевантных пакетов (например `util-linux`, `wb-mqtt-serial`), uptime, что подключено (Modbus-устройства, Z2M, Docker-проекты), severity.
2. **Действия** — что делали (или «штатная работа без вмешательства»).
3. **Ожидание** — что должно было произойти.
4. **Факт** — что произошло, с цитатами `journalctl`/`systemctl status`. Указывай абсолютные timestamps.
5. **Воспроизводимость** — да/нет, как часто, периодичность (для systemd-таймеров — даты падений).
6. **Минимальная конфигурация** — можно ли отключить лишнее, чтобы локализовать.
7. **Что уже пробовали** — обходные пути (если есть).
8. **Желательный исход** — фикс в пакете, override-юнит, изменение FIT-сборки.
9. **Диагностика** — имя diag-архива (если есть) и его SHA-256, ссылки на логи.
```

Покажи пользователю для проверки.

## Связанные скиллы

- `/troubleshooting` — общая диагностика (kernel mismatch, диск, failed-юниты, журнал ошибок) — часть шага 1 дублирует его команды; если копаешь глубже, перейди сразу в него.
- `/troubleshooting-serial` — если симптом про Modbus/RS-485 (CRC, timeout) — там debug-сессия и `wb-diag-collect` не нужен.
- `/controller-backup` — обязательный страховочный snapshot перед любыми изменениями `/etc/*` для проверки гипотезы.
- `/controller-update` — если гипотеза «починилось бы свежим пакетом», проверяй через recon из `/controller-update` (не запуская реальный upgrade).
- `/wiren-board` — мастер-скилл; если первая ssh-команда падает с `Could not resolve hostname`, прогрев mDNS оттуда (`echo "$(timeout 5 avahi-browse -arp 2>/dev/null)"`).
