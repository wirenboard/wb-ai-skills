---
name: bugreport
description: Составление багрепорта для поддержки Wiren Board через MCP — сбор данных, диагархив, оформление.
allowed-tools: Bash Read Write WebFetch
---

# bugreport (MCP)

Составление багрепорта для службы поддержки Wiren Board через MCP-tools.

## Принцип

Максимум собери сам через MCP-tools (`wb_probe`, `wb_audit`, `wb_failed`, `wb_logs`); минимум спрашивай. Список в шаге 4 — **запасной вариант** для пунктов, которые автодиагностика не закрыла.

**Перед изменением чего-либо** на продакшн-контроллере для проверки гипотезы — `wb_state_save` (короткий снапшот, см. `/controller-backup`).

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| HW + версия прошивки + релиз | `wb_probe` |
| Аудит: пакеты, сервисы, кастомные файлы | `wb_audit` |
| Метрики: load, RAM, диск | `wb_metrics` |
| Список упавших unit'ов | `wb_failed` |
| Логи конкретного сервиса | `wb_logs` |
| Журнал ошибок (priority=err за период) | `wb_ssh_exec` `journalctl -p err --since "1 hour ago" --no-pager` |
| Снимок «до бага» (если воспроизводится после действия) | `wb_state_save` |
| Diff состояния | `wb_state_diff` |
| Сбор diag-архива (`wb-diag-collect`, минуты) | `wb_ssh_exec_async` |

## Порядок

### 1. Собери паспорт контроллера

- `wb_probe sn=<SN>` — SN, hostname, релиз, ядро, fw, uptime.
- `wb_metrics sn=<SN>` — диск, нагрузка, память.
- `wb_failed sn=<SN>` — упавшие сервисы.
- `wb_ssh_exec sn=<SN> cmd='journalctl -p err --since "1 hour ago" --no-pager'` — ошибки за последний час.

Если проблема с конкретным сервисом:
```
wb_ssh_exec sn=<SN> cmd='systemctl status <unit> --no-pager'
wb_logs sn=<SN> unit=<unit> lines=100
```

Kernel mismatch (частая причина проблем после обновления): `wb_ssh_exec sn=<SN> cmd='echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" | grep ^ii'`. Или просто `wb_audit` — отметит расхождение.

Дрейф пакетов и кастомные файлы: `wb_audit sn=<SN>`.

### 2. Собери диагностический архив (если нужен)

`wb-diag-collect <prefix>` принимает **префикс имени файла**, не директорию. Реальный файл попадает в **родительский каталог префикса** под именем `<prefix>_<SN>_<TS>.zip`.

```
wb_ssh_exec sn=<SN> cmd='mkdir -p /mnt/data/ai/wb-ai-integration'
wb_ssh_exec_async sn=<SN> cmd='wb-diag-collect /mnt/data/ai/wb-ai-integration/diag'
```

Подожди завершения (`wb_job_status job_id=<id>` → `exited`). Найди реальное имя:

```
wb_ssh_exec sn=<SN> cmd='ls -t /mnt/data/ai/wb-ai-integration/diag_*.zip 2>/dev/null | head -1'
```

Скачай **только последний** архив локальным `scp` (он сотни КБ — `wb_read_file` упадёт на 64 КБ):

```bash
scp root@wirenboard-<SN>.local:<полный путь из ls> /tmp/<SN>-bugreport-$(date +%Y-%m-%d).zip
```

Не делай `scp ...:/.../diag*.zip ./` — глоб развернётся на удалённой стороне и скачает все старые архивы.

**Что покрывает diag-архив:**
- `last_logs.log` / `last_logs.previous-boot.log` — журнал текущего и предыдущего boot.
- `dmesg.log` / `dmesg.previous-boot.log` — kernel ring buffer.
- `service/<unit>.service.log` — журнал по каждому **WB-сервису** (mosquitto, wb-mqtt-*, wb-rules, wb-device-manager и т.п.).
- `etc/`, `usr/lib/`, `static/` — конфиги, версии, описание ревизии.
- `dpkg_l.log`, `df_h.log`, `free.log`, `ps_aux.log`, NetworkManager-конфиги, eMMC EXT_CSD.

**Чего НЕТ в архиве** (нужно собирать отдельно):
- Не-WB systemd-юниты (`fstrim.service`, кастомные `*.service`).
- Логи Docker-контейнеров (`nodered`, `zigbee2mqtt`-в-Docker и т.п.).
- Долгопериодные выборки по приоритету (за неделю/месяц).
- Снимки MQTT-состояния.

**Прицельный сбор того, чего нет в архиве:**

```
# Журнал не-WB юнита целиком (укажи unit):
wb_logs sn=<SN> unit=<unit> lines=500
# Или если нужен длинный период с фильтром:
wb_ssh_exec sn=<SN> cmd='journalctl -u <unit> --no-pager --since "1 month ago"'

# Логи Docker-контейнера:
wb_ssh_exec sn=<SN> cmd='docker logs --tail 1000 --timestamps <container>'

# Все ошибки за неделю:
wb_ssh_exec sn=<SN> cmd='journalctl -p err --since "7 days ago" --no-pager'

# Снимок MQTT-состояния (для багов про устройства):
wb_mqtt_devices sn=<SN>
wb_mqtt_list sn=<SN> prefix=zigbee2mqtt/bridge/
```

В багрепорт прикладывай **архив + дополнительно собранные логи** под понятными именами.

**Когда архив не нужен:** для упавшего systemd-юнита часто достаточно `wb_logs unit=<unit>` + `wb_ssh_exec` `systemctl status <unit>; systemctl cat <unit>`. Архив на сотни КБ — нагрузка на eMMC; собирай если поддержка попросит или если причина не локализована за 5 минут.

### 3. Опиши проблему

Из контекста диалога ты уже знаешь, что произошло. Опиши сам, не переспрашивая.

### 4. Спроси только то, что **нельзя** узнать с контроллера

Этот список — запасной. Сначала проверь сам через tools.

- **Severity** и контекст: продакшн или стенд.
- **Физическое подключение** (фото шины, тип БП — если проблема с оборудованием).
- **Что видит в браузере/на экране** (скриншот — если проблема UI).
- **Воспроизводимость** — если в логах не очевидно по таймштампам.
- **Что уже пробовали** для обхода.
- **Желательный исход**: фикс в пакете / временный обход / можно ли вечером перезагрузить.
- **Куда вернётся ответ**: тикет в support@wirenboard.com / форум / телеграм.

Спрашивай одним списком.

### 5. Оформи багрепорт

Шаблон:

```
**Тема:** <SN> — <короткий симптом одной строкой>

1. **Оборудование** — SN, релиз (`wb-XXXX`/target), ядро, fw, версии релевантных пакетов (например `util-linux`, `wb-mqtt-serial`), uptime, что подключено (из `wb_probe`+`wb_audit`+`wb_mqtt_devices`), severity.
2. **Действия** — что делали (или «штатная работа без вмешательства»).
3. **Ожидание** — что должно было произойти.
4. **Факт** — что произошло, с цитатами `journalctl`/`systemctl status`. Абсолютные timestamps.
5. **Воспроизводимость** — да/нет, как часто, периодичность (для systemd-таймеров — даты падений).
6. **Минимальная конфигурация** — можно ли отключить лишнее.
7. **Что уже пробовали** — обходные пути.
8. **Желательный исход** — фикс в пакете / override-юнит / изменение FIT-сборки.
9. **Диагностика** — имя diag-архива (если есть) и SHA-256, отличия от стока (`wb_audit`), `wb_state_diff` если есть снимок.
```

Покажи пользователю для проверки.

## Связанные скиллы

- `/troubleshooting` — общая диагностика (kernel mismatch, диск, failed-юниты).
- `/troubleshooting-serial` — если симптом про Modbus/RS-485 (debug-сессия + scan, не diag-архив).
- `/controller-backup` — страховочный snapshot перед любыми изменениями `/etc/*`.
- `/controller-update` — recon без upgrade, чтобы проверить «починилось бы свежим пакетом».
- `/wiren-board` — мастер с прогревом mDNS и общим SSH-этикетом.
