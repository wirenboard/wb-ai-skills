---
name: controller-update
description: Обновление пакетов WB (apt upgrade) и переключение релизов (wb-release -t) через MCP. Recon, HITL, verify.
allowed-tools: Bash Read Write WebFetch
---

# controller-update (MCP)

Обновление пакетов контроллера WB и переход между релизами через `apt` и `wb-release -t`. Все долгие команды — через `wb_ssh_exec_async`. Синхронный `wb_ssh_exec` упадёт по таймауту, оборвав apt в середине транзакции.

**FIT-прошивку НЕ запускаем** (wb-fw-update, swupdate) — только через web UI контроллера.

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Текущий релиз / версия прошивки | `wb_probe` или `wb_ssh_exec` `wb-release` |
| Свободное место и нагрузка | `wb_metrics` |
| Список upgradable пакетов | `wb_ssh_exec` `apt list --upgradable` (после `apt-get update`) |
| `apt-get update`, `apt-get upgrade`, `apt-get dist-upgrade` | `wb_ssh_exec_async` |
| `wb-release -t <release>` (смена релиза) | `wb_ssh_exec_async` |
| Прогресс задачи | `wb_job_tail` |
| Статус задачи | `wb_job_status` |
| Отмена (только до критической фазы установки) | `wb_job_cancel` |
| Снимок состояния «до» | `wb_state_save` |
| Diff после обновления | `wb_state_diff` |
| Упавшие unit'ы после | `wb_failed` |
| Логи ключевых сервисов после | `wb_logs` |
| Бэкап перед сменой релиза | скилл `/controller-backup` |

## Recon — всегда первым

```
wb_ssh_exec sn=<SN> cmd='echo === RELEASE ===; wb-release 2>&1; echo === KERNEL ===; echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" | grep ^ii | awk "{print \"installed:\", \$3}"'
wb_metrics sn=<SN>                               # нагрузка, RAM, диск
wb_ssh_exec sn=<SN> cmd='apt-get update 2>&1 | tail -20'    # синхронно ОК — apt update идёт 2-5 сек
wb_ssh_exec sn=<SN> cmd='apt list --upgradable 2>/dev/null'
```

Не обрезай вывод `apt list` — wb-пакеты в конце алфавита.

**Свободное место на `/`:** `>= 1 ГБ` норма; `500 МБ — 1 ГБ` для крупного апгрейда требует `wb_ssh_exec` `apt-get clean; journalctl --vacuum-time=3d`; `< 500 МБ` критично — освобождать.

**Kernel mismatch до апгрейда** = сначала reboot, потом recon заново (см. `/troubleshooting`).

`wb_state_save sn=<SN>` — снимок состояния «до», чтобы потом сделать `wb_state_diff`.

**Подсчёт «N upgradable, M wb-*»:**
```
wb_ssh_exec sn=<SN> cmd='apt list --upgradable 2>/dev/null | tail -n +2 | sort -u | wc -l; apt list --upgradable 2>/dev/null | tail -n +2 | grep -cE "^(wb-|task-wirenboard|task-wb|libwbmqtt|frpc|knxd|telegraf-wb|u-boot-wb|linux-image-wb)"'
```
`sort -u` снимает multiarch-дубли (один пакет в arm64+armhf — это один пакет).

### Major-version риски

После recon найди мажорные апгрейды и подсветь пользователю — они не идут в общий поток:

| Пакет | Когда мажорный | Действие |
|-------|----------------|----------|
| `docker-ce`, `containerd.io`, `docker-compose-plugin` | смена major | Отдельным апгрейдом после обычного, после ревью compose-файлов |
| `u-boot-wb*` | смена major | Прочитать changelog пакета, согласовать |
| `linux-image-wb*` | любая | Reboot после апгрейда обязателен, заранее предупредить |
| `wb-rules`, `wb-mqtt-serial` со скачком >5 минорных | большой gap | Прочитать релиз-ноты — могут поменяться форматы конфигов |

## Сценарий A: обновление пакетов

Триггеры: «обнови пакеты», «apt upgrade», «есть обновления?»

1. Покажи пользователю список upgradable. **Жди подтверждения.**
2. Запусти:

   ```
   wb_ssh_exec_async sn=<SN> cmd='DEBIAN_FRONTEND=noninteractive apt-get -y upgrade'
   ```

3. Следи через `wb_job_tail job_id=<id>`.
4. **Проверь kept-back.** Если часть пакетов осталась — предложи `dist-upgrade` (показав, что будет):

   ```
   wb_ssh_exec_async sn=<SN> cmd='apt-get -s dist-upgrade | grep -E "^(Inst|Remv)"'
   ```

   **Жди подтверждения.**

5. Если обновилось ядро (`linux-image`) — предупреди: «Нужна перезагрузка для нового ядра.» Жди подтверждения, потом:

   ```
   wb_ssh_exec sn=<SN> cmd='systemctl reboot'
   ```

6. Проверь: `wb_failed`, `wb_logs unit=wb-rules lines=20`, `wb_state_diff` против снимка «до».

## Сценарий B: смена релиза (stable↔testing)

Триггеры: «перейди на testing», «сменить suite».

**Только для stable↔testing. Обновление на новый stable — через apt upgrade (сценарий A).**

1. Узнай точное имя целевого релиза: `WebFetch https://wirenboard.com/wiki/WB_Software_Releases`.
2. Сделай бэкап: вызови `/controller-backup`.
3. **Жди подтверждения** с указанием целевого релиза.
4. Запусти:

   ```
   wb_ssh_exec_async sn=<SN> cmd='wb-release -y -t <target>'
   ```

5. SSH может временно отвалиться (рестарт сети). Процесс продолжает идти (фоновая задача переживает разрыв). `wb_job_status` будет `running`. Подожди и повтори `wb_probe` / `wb_job_tail`.
6. После: `wb_ssh_exec` `wb-release; apt list --upgradable`, `wb_failed`, `wb_state_diff`.

## Сценарий C: просто проверить обновления

Recon-команды выше. Никаких upgrade. Отчёт: текущий релиз, N upgradable, из них M — wb-*.

## Сценарий D: factory reset (заводское состояние)

⚠️ **Деструктивно. Стирает ВСЁ:** конфиги, пользовательские данные, кастомные пакеты, Docker-образы, правила, шаблоны. После reset SSH host-key контроллера изменится, пароль root вернётся к заводскому (`wirenboard`). Кастомный SSH-ключ root'а пропадёт — ssh-copy-id заново. (MCP-сервер использует `StrictHostKeyChecking=no`, так что после factory reset продолжит подключаться без `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`.)

Программный путь — `/usr/bin/wb-factoryreset --force`:

1. **Бэкап обязателен** (вызови `/controller-backup` целиком, скачай локально):
   ```
   /controller-backup
   ```
   После reset восстановиться можно ТОЛЬКО из этого архива. **`/mnt/data/ai/` тоже стирается** — snapshot из `wb_state_save` исчезнет, `wb_state_diff` после reset невозможен. Если нужен diff — скачай snapshot файл локально перед reset (через `wb_read_file` или `scp`).

2. **Явное подтверждение пользователя** — со ссылкой на потерю данных и кастомного SSH-ключа. Не запускай по неоднозначной формулировке.

3. **Запуск через async** (синхронный wb_ssh_exec упадёт по таймауту, sleep 60 + reboot):
   ```
   wb_ssh_exec_async sn=<SN> cmd='/usr/bin/wb-factoryreset --force'
   ```

   Скрипт внутри:
   - проверяет `firmware-compatible: fit-factory-reset`,
   - создаёт флаг `/mnt/data/.wb-update/wb_use_factory_fit.flag`,
   - ждёт ~60 сек до инициации FIT-прошивки `wb-watch-update`'ом и reboot.

4. **Контроллер недоступен 2-5 минут.** SSH-сессия отвалится. После reboot повтори `wb_probe sn=<SN>` — пока не вернёт ОК.

5. **После загрузки**: пароль root — `wirenboard`, host-key новый (MCP-сервер примет, см. выше), кастомные ключи пропали — `ssh-copy-id` заново если нужно.

6. **Восстановление** — по `RESTORE.md` из бэкапа.

**Если прошивка не поддерживает factory reset** — `wb-factoryreset` напишет «not supported by this firmware». Это старая прошивка, factory reset делается только через web UI / Recovery USB.

## Грабли

- **`apt-get update`** идёт 2-5 секунд (только обновление индексов) — `wb_ssh_exec` синхронно ок. **`apt-get upgrade` / `dist-upgrade` / `wb-release -t`** — длинные, **только** `wb_ssh_exec_async`. Не путай.
- `wb-release -t` без `-y` — повиснет в ожидании stdin.
- Не бэкапить перед сменой релиза — кастомные конфиги могут сломаться.
- Reboot в середине `apt upgrade` — сломает dpkg.
- После смены релиза не проверить `wb_failed` — пропустишь упавшие сервисы.
- Проигнорировать мажорный апгрейд (Docker, containerd, u-boot, linux-image) — по ломающим изменениям пользователь должен решать сам.
- Не учесть multiarch — `apt list --upgradable | wc -l` посчитает arm64 и armhf-варианты одного пакета как два. Используй `sort -u`.

## Документация

- Релизы: <https://github.com/wirenboard/wb-releases/blob/master/README.md>
- Wiki: <https://wirenboard.com/wiki/WB_Software_Releases>
- Update: <https://wirenboard.com/wiki/Wirenboard_Update>
