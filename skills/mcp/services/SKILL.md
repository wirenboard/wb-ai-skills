---
name: services
description: Управление systemd-сервисами и таймерами на контроллере Wiren Board через MCP. Override-conf, drop-ins, кастомные юниты и таймеры, enable/disable/mask. НЕ для диагностики (для диагностики `/troubleshooting`).
allowed-tools: Bash Read Write WebFetch
---

# services (MCP)

systemd на контроллере WB через MCP-tool `wb_systemd_unit` + `wb_write_file` для override-conf и кастомных юнитов.

Подгружай при: «сделай сервис из моего скрипта», «добавь таймер на бэкап», «отмаскировать `<unit>`», «сделать override на ExecStart», «после рестарта пакета мой override пропадает», «таймер не срабатывает».

**Не путай с `/troubleshooting`** (упавшие сервисы, kernel mismatch, журнал) и `/controller-update` (apt upgrade).

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Статус юнита (parsed) | `wb_systemd_unit unit=<u>` (action=status по умолчанию) |
| Содержимое юнита со всеми drop-ins | `wb_systemd_unit unit=<u> action=cat` |
| Зависимости юнита | `wb_systemd_unit unit=<u> action=list-deps` |
| Старт / стоп / рестарт / reload | `wb_systemd_unit unit=<u> action=start|stop|restart|reload` |
| Включить / выключить автозагрузку | `wb_systemd_unit unit=<u> action=enable|disable` |
| Маска (запрет запуска) | `wb_systemd_unit unit=<u> action=mask|unmask` |
| Логи юнита | `wb_logs unit=<u>` (с `since`/`grep` если нужно) |
| Записать override.conf или кастомный юнит | `wb_write_file path=/etc/systemd/system/<unit>.service.d/override.conf` или `/etc/systemd/system/<unit>.service` |
| `daemon-reload` после правки .service/.timer | `wb_ssh_exec` `systemctl daemon-reload` |
| Список таймеров и следующих срабатываний | `wb_ssh_exec` `systemctl list-timers --no-pager` |

## Сценарий: override на пакетный юнит

1. `wb_systemd_unit unit=<u> action=cat` — посмотреть текущий .service и существующие drop-ins.
2. `wb_write_file path=/etc/systemd/system/<u>.service.d/override.conf` — drop-in.
3. `wb_ssh_exec` `systemctl daemon-reload`.
4. `wb_systemd_unit unit=<u> action=restart`.
5. `wb_systemd_unit unit=<u>` — статус, проверить что ExecStart/Restart применились.

**Сброс директивы из основного файла** — повторное объявление пустой строкой:

```ini
[Service]
ExecStart=
ExecStart=/usr/local/bin/my-wrapped-service
```

Без `ExecStart=` (пустая) systemd добавит новую к старой.

## Сценарий: создать сервис из скрипта

1. `wb_write_file path=/usr/local/bin/<name>.sh content=<bash>` + `wb_ssh_exec chmod 0755 ...`.
2. `wb_write_file path=/etc/systemd/system/<name>.service content=<unit>`.
3. `wb_ssh_exec` `systemctl daemon-reload`.
4. `wb_systemd_unit unit=<name> action=start` — проверить.
5. `wb_systemd_unit unit=<name>` — статус.

**Минимальный шаблон oneshot-сервиса под таймер:**

```ini
[Unit]
Description=My periodic task
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/my-task.sh
StandardOutput=journal
StandardError=journal
```

## Сценарий: таймер

1. `wb_write_file path=/etc/systemd/system/<name>.timer content=<timer>`.
2. `wb_ssh_exec` `systemctl daemon-reload`.
3. `wb_systemd_unit unit=<name>.timer action=enable` (затем `action=start` или сразу через `wb_ssh_exec` `systemctl enable --now <name>.timer`).
4. `wb_ssh_exec` `systemctl list-timers <name>.timer --no-pager` — увидеть `NEXT`.

**Шаблон таймера:**

```ini
[Unit]
Description=Run my-task every hour

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=2min

[Install]
WantedBy=timers.target
```

`Persistent=true` — догонит запуск, если контроллер был выключен.

## wb-rules cron vs systemd timer

| Случай | Выбирать |
|--------|---------|
| Условие зависит от MQTT-состояния, dev[], других правил | `/wb-rules` cron(...) или setInterval |
| Простой shell-скрипт по расписанию | systemd timer (этот скилл) |
| Бэкап / синхронизация / мониторинг (не привязано к шине) | systemd timer |
| Реакция на изменение контрола или события шины | `/wb-rules` whenChanged |

## Грабли

- **Правка `/lib/systemd/system/<u>.service` напрямую** — затрут apt'ом. Только drop-in в `/etc/systemd/system/<u>.service.d/`.
- **`ExecStart=` в drop-in без сброса** — пустая строка перед новой обязательна.
- **Забыл `systemctl daemon-reload`** — systemd не видит изменений.
- **`enable` без `--now`** — юнит активируется только после reboot. Делай `wb_systemd_unit action=enable` + `action=start` отдельно, или `wb_ssh_exec` `systemctl enable --now <u>`.
- **Type=oneshot без `RemainAfterExit=yes`** — после успешного выполнения «inactive (dead)». Нормально для таймера, но не для постоянно-запущенного.
- **Кастомный юнит без `[Install]`** — `enable` упадёт «No installation information found».
- **mask забыл `unmask`** — потом не запускается.
- **Кастомные юниты в `/etc/systemd/system/`** не переживают FIT-прошивку. Для бэкапа — `/controller-backup` (секция «Кастомные systemd-юниты»).

## Связанные скиллы

- `/troubleshooting` — диагностика упавших юнитов, kernel mismatch.
- `/wb-rules` — автоматизация, реагирующая на MQTT.
- `/controller-backup` — сохранение кастомных юнитов перед FIT.

Подробности (override-синтаксис, full примеры, OnCalendar) — bash-двойник `/services` (одноимённый skill, bash-flavor).

## Документация

- systemd unit: <https://www.freedesktop.org/software/systemd/man/systemd.unit.html>
- systemd timer: <https://www.freedesktop.org/software/systemd/man/systemd.timer.html>
- OnCalendar: <https://www.freedesktop.org/software/systemd/man/systemd.time.html>
