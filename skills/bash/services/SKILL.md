---
name: services
description: Управление systemd-сервисами и таймерами на контроллере Wiren Board. Создание override-conf, drop-ins, кастомных юнитов и таймеров. Включение, выключение, маска. НЕ для диагностики (для диагностики `/troubleshooting`).
allowed-tools: Bash Read Write WebFetch
---

# services

systemd на контроллере Wiren Board: управление существующими юнитами, создание собственных сервисов и таймеров, override-conf для пакетных юнитов.

Подгружай при: «сделай сервис из моего скрипта», «добавь таймер на бэкап», «отмаскировать `<unit>`», «сделать override на ExecStart», «после рестарта пакета мой override пропадает», «таймер не срабатывает», «как сделать чтобы при загрузке…».

**Не путай с `/troubleshooting`** (упавшие сервисы, kernel mismatch, журнал) и `/controller-update` (apt upgrade).

## Базовые команды

```bash
ssh root@<HOST> 'systemctl is-active <unit>'
ssh root@<HOST> 'systemctl status <unit> --no-pager'
ssh root@<HOST> 'systemctl cat <unit>'                # все .service-файлы и drop-ins, какие реально применяются
ssh root@<HOST> 'systemctl show <unit> -p ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths --no-pager'
ssh root@<HOST> 'systemctl list-dependencies <unit> --no-pager'
ssh root@<HOST> 'journalctl -u <unit> -n 50 --no-pager'   # см. также `/troubleshooting`
```

`systemctl status` для failed-юнита возвращает exit 3 — это **код состояния, не ошибка ssh**.

## Override-conf (drop-in) — правильный способ менять пакетный юнит

Никогда не редактируй `/lib/systemd/system/<unit>.service` напрямую — apt перезапишет при апгрейде. Используй drop-in:

```bash
ssh root@<HOST> 'mkdir -p /etc/systemd/system/<unit>.service.d'
ssh root@<HOST> 'cat > /etc/systemd/system/<unit>.service.d/override.conf' <<'EOF'
[Service]
Restart=on-failure
RestartSec=10s
EOF
ssh root@<HOST> 'systemctl daemon-reload && systemctl restart <unit>'
```

**Чтобы очистить директиву из основного файла, повторно объяви её пустой**:

```ini
[Service]
ExecStart=
ExecStart=/usr/local/bin/my-wrapped-service
```

(Первая строка с пустым значением сбрасывает старую `ExecStart`, вторая ставит новую. Без сброса systemd добавит вторую к первой.)

Применить и проверить: `daemon-reload`, `restart`, `systemctl cat <unit>` (виден ли drop-in), `systemctl show <unit> -p ExecStart`.

### fstrim.service / `status=64/USAGE` пример override

```bash
ssh root@<HOST> 'mkdir -p /etc/systemd/system/fstrim.service.d'
ssh root@<HOST> 'cat > /etc/systemd/system/fstrim.service.d/override.conf' <<'EOF'
[Service]
ExecStart=
ExecStart=/sbin/fstrim --fstab --quiet-unsupported
EOF
ssh root@<HOST> 'systemctl daemon-reload && systemctl reset-failed fstrim.service'
```

`--quiet-unsupported` пропускает физически отсутствующие точки (типичный кейс — `/mnt/sdcard` без SD).

## Создать собственный сервис из скрипта

1. **Скрипт** — положи в `/usr/local/bin/<name>.sh`, владелец root, mode 0755:

```bash
ssh root@<HOST> 'cat > /usr/local/bin/my-task.sh' <<'EOF'
#!/bin/bash
set -e
echo "[$(date -Is)] doing the thing"
# ... работа ...
EOF
ssh root@<HOST> 'chmod 0755 /usr/local/bin/my-task.sh'
```

2. **Юнит** — `/etc/systemd/system/<name>.service`:

```bash
ssh root@<HOST> 'cat > /etc/systemd/system/my-task.service' <<'EOF'
[Unit]
Description=My periodic task
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/my-task.sh
StandardOutput=journal
StandardError=journal
EOF
ssh root@<HOST> 'systemctl daemon-reload'
```

`Type=oneshot` — для одноразовых задач (типичный кейс под таймер). Для долгоживущих сервисов — `Type=simple` (по умолчанию) или `Type=notify` (если бинарник умеет sd_notify).

3. **Запустить руками для проверки**:

```bash
ssh root@<HOST> 'systemctl start my-task && systemctl status my-task --no-pager -n 20'
```

## Создать таймер

Таймер — отдельный юнит `<name>.timer`, который запускает одноимённый `<name>.service` (или другой через `Unit=`).

```bash
ssh root@<HOST> 'cat > /etc/systemd/system/my-task.timer' <<'EOF'
[Unit]
Description=Run my-task every hour

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=2min

[Install]
WantedBy=timers.target
EOF
ssh root@<HOST> 'systemctl daemon-reload && systemctl enable --now my-task.timer'
```

- `OnCalendar=hourly` — раз в час (`@hourly` в cron). Полный синтаксис: `OnCalendar=*-*-* 03:00:00` (ежедневно в 03:00), `Mon..Fri 08:00`, `*-*-1 12:00` (1-го числа в 12:00). Проверка: `systemd-analyze calendar 'Mon..Fri 08:00'`.
- `Persistent=true` — если контроллер был выключен в момент срабатывания, таймер запустится сразу при загрузке.
- `RandomizedDelaySec` — рандомизация запуска (полезно когда несколько контроллеров стучатся в один сервер).

`OnBootSec=2min` / `OnUnitActiveSec=10min` — альтернативы для «через X после загрузки» / «каждые X после прошлого срабатывания».

**Список таймеров и следующее срабатывание**:

```bash
ssh root@<HOST> 'systemctl list-timers --no-pager'
```

## wb-rules cron vs systemd timer

| Случай | Что выбирать |
|--------|--------------|
| Условие зависит от MQTT-состояния, dev[], таймеров и других правил | wb-rules `cron(...)` или `setInterval` (см. `/wb-rules`) |
| Простой запуск shell-команды по расписанию | systemd timer (этот скилл) |
| Бэкап, синхронизация, мониторинг — задача не привязана к шине | systemd timer |
| Нужен запуск задачи при загрузке + потом ежедневно | systemd timer (`OnBootSec=` + `OnCalendar=`) |
| Реакция на изменение контрола / событие шины | wb-rules `whenChanged` (не cron вообще) |

## Включение / выключение / маска

```bash
ssh root@<HOST> 'systemctl enable <unit>'      # автозагрузка
ssh root@<HOST> 'systemctl disable <unit>'     # снять автозагрузку
ssh root@<HOST> 'systemctl mask <unit>'        # запретить запуск (даже зависимостями) — симлинк в /dev/null
ssh root@<HOST> 'systemctl unmask <unit>'      # отменить mask
ssh root@<HOST> 'systemctl reset-failed <unit>'  # снять статус failed (без рестарта)
```

`mask` сильнее `disable` — он делает юнит «несуществующим», даже зависящие от него сервисы не запустят его. Используй когда нужно выключить пакетный сервис, который иначе запускают другие сервисы (например, отключить `bluetooth.service` на безголовых контроллерах).

## Список enabled-юнитов

```bash
ssh root@<HOST> 'systemctl list-unit-files --state=enabled --no-legend | awk "{print \$1}" | sort'
```

Для понимания «что лишнее работает» — сверяй с типовым набором WB.

## После пакетного апгрейда

Override и кастомные юниты в `/etc/systemd/system/` **переживают** apt upgrade — пакет может изменить `/lib/systemd/system/<unit>.service`, но drop-in остаётся в силе.

Если после апгрейда пакетный юнит «не подцепил» override — `systemctl daemon-reload && systemctl restart <unit>`.

**Кастомные юниты в `/etc/systemd/system/`** не переживают FIT-прошивку (она перезаписывает rootfs). Для бэкапа — см. `/controller-backup`, секция «Кастомные systemd-юниты».

## Грабли

- **Правка `/lib/systemd/system/<unit>.service` напрямую** — затрут apt'ом. Только drop-in.
- **`ExecStart=` в drop-in без сброса** — добавит вторую команду к первой. Сначала пустая строка `ExecStart=`, потом новая.
- **Забыл `daemon-reload`** — systemd не видит изменений. После любой правки .service/.timer.
- **`enable` без `--now`** — юнит включён, но не стартанул в этой сессии. `enable --now` или отдельный `start`.
- **`OnCalendar` неправильно** — проверяй через `systemd-analyze calendar '<expr>'` перед заливкой.
- **Type=oneshot без `RemainAfterExit=yes`** — после успешного выполнения юнит «inactive (dead)», а не active. Это нормально для таймера, но если ты ожидаешь увидеть active — поставь `RemainAfterExit=yes`.
- **Кастомный юнит без `[Install]` секции** — `enable` упадёт «No installation information found».
- **mask без unmask потом** — забытые маски ломают сервисы при следующем апгрейде.

## Документация

- systemd unit syntax: <https://www.freedesktop.org/software/systemd/man/systemd.unit.html>
- systemd timer syntax: <https://www.freedesktop.org/software/systemd/man/systemd.timer.html>
- OnCalendar формат: <https://www.freedesktop.org/software/systemd/man/systemd.time.html>
