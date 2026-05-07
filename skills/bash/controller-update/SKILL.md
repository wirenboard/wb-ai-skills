---
name: controller-update
description: Обновление пакетов WB (apt upgrade) и переключение релизов (wb-release -t). Recon, HITL, verify.
allowed-tools: Bash Read Write WebFetch
---

# controller-update

Обновление пакетов контроллера WB и переход между релизами через `apt` и `wb-release -t`.

**FIT-прошивку НЕ запускаем** (wb-fw-update, swupdate) — только через web UI контроллера.

## Recon — всегда первым

```bash
# Шаг 1: текущее состояние + kernel mismatch (mismatch — частая причина проблем после обновления; см. /troubleshooting)
ssh root@<HOST> 'echo === RELEASE ===; wb-release 2>&1; echo === KERNEL ===; echo "running: $(uname -r)"; dpkg -l "linux-image-wb*" 2>/dev/null | grep ^ii | awk "{print \"installed:\", \$3}"; echo === DISK ===; df -h / /mnt/data | awk "NR==1 || /\/$|\/mnt\/data/"; echo === UPTIME ===; uptime'

# Шаг 2: обновление кеша apt (синхронно ОК — apt-get update идёт 2-5 сек, не путать с apt upgrade)
ssh root@<HOST> 'apt-get update 2>&1 | tail -20; echo ===; apt list --upgradable 2>/dev/null'
```

Не обрезай `apt list` — wb-пакеты в конце алфавита.

**Свободное место на `/`:**
- `>= 1 ГБ` — норма для апгрейда любого размера.
- `500 МБ — 1 ГБ` — пограничная зона, для крупного апгрейда (95+ пакетов или с linux-image) сначала чистка: `apt-get clean; journalctl --vacuum-time=3d`.
- `< 500 МБ` — критично, апгрейд может не завершиться. Сначала освободить.

**Kernel mismatch:** если running и installed расходятся **до** апгрейда — сначала reboot, потом recon снова. После апгрейда новой `linux-image-wb*` mismatch появится естественно, и reboot потребуется уже после.

**Подсчёт «N upgradable, M wb-*»** для отчёта в Сценарии C:
```bash
ssh root@<HOST> 'apt list --upgradable 2>/dev/null | tail -n +2 | sort -u | wc -l; apt list --upgradable 2>/dev/null | tail -n +2 | grep -cE "^(wb-|task-wirenboard|task-wb|libwbmqtt|frpc|knxd|telegraf-wb|u-boot-wb|linux-image-wb)"'
```
`sort -u` снимает multiarch-дубли (`pkg/x.y.z arm64` и `pkg/x.y.z armhf` — это один пакет в двух архитектурах, учитывай как один). Префикс-фильтр для wb-* — эвристика; уточняй по конкретному списку.

### Major-version риски

После шага 2 пройдись глазами по списку: **мажорные апгрейды** требуют отдельного решения, не идут в общий поток.

| Пакет | Когда мажорный | Что делать |
|-------|----------------|-----------|
| `docker-ce`, `containerd.io`, `docker-compose-plugin` | смена major (28→29, 1→2, 2→5) | Рестарт демона + ломающие изменения compose-схемы. Прочитай changelog, согласуй с пользователем, делай отдельным апгрейдом после обычного |
| `u-boot-wb*` | смена major (2021→2025) | На WB пакет обычно содержит образ для FIT, не флешит сам. Но проверить changelog обязательно — возможны новые требования к окружению |
| `linux-image-wb*` | любая смена | Reboot нужен, kernel mismatch до перезагрузки |
| `wb-rules`, `wb-mqtt-serial` со скачком >5 минорных версий | большой gap (например 2.180 → 2.224) | Прочитать релиз-ноты — могут поменяться форматы конфигов |

Подсветь это пользователю в ответе на recon — не запускай `apt upgrade` молча через головы мажорных скачков.

## Сценарий A: обновление пакетов

Триггеры: «обнови пакеты», «apt upgrade», «есть обновления?»

1. Покажи пользователю список upgradable. **Жди подтверждения.**
2. Запусти:
```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-upgrade --collect bash -c "DEBIAN_FRONTEND=noninteractive apt-get -y upgrade"'
```
3. Следи: `ssh root@<HOST> 'systemctl status wb-ai-upgrade; journalctl -u wb-ai-upgrade --no-pager | tail -30'`
4. **Проверь kept-back.** Если часть пакетов осталась — предложи `dist-upgrade` (показав что будет: `apt-get -s dist-upgrade | grep -E '^(Inst|Remv)'`). **Жди подтверждения.**
5. Если обновилось ядро (`linux-image`) — предупреди: «Нужна перезагрузка для нового ядра.» Жди подтверждения, потом `ssh root@<HOST> 'systemctl reboot'`.
6. Проверь: `systemctl --failed`, `journalctl -u wb-rules -n 20 --no-pager`

## Сценарий B: смена релиза (stable↔testing)

Триггеры: «перейди на testing», «сменить suite»

**Только для stable↔testing. Обновление на новый stable — через apt upgrade (сценарий A).**

1. Узнай точное имя целевого релиза: `WebFetch https://wirenboard.com/wiki/WB_Software_Releases`
2. Сделай бэкап: `/controller-backup`
3. **Жди подтверждения** с указанием целевого релиза.
4. Запусти:
```bash
ssh root@<HOST> 'systemd-run --unit=wb-ai-release --collect bash -c "wb-release -y -t <target>"'
```
5. SSH может временно отвалиться (рестарт сети). Процесс продолжает идти (`systemd-run --collect`). Подожди и повтори проверку.
6. После: `wb-release`, `apt list --upgradable`, `systemctl --failed`

## Сценарий C: просто проверить обновления

Recon-команды выше. Никаких upgrade. Отчёт: текущий релиз, N upgradable, из них M — wb-*.

## Сценарий D: factory reset (заводское состояние)

⚠️ **Деструктивно. Стирает ВСЁ:** конфиги, пользовательские данные, кастомные пакеты, Docker-образы, правила, шаблоны. После reset SSH host-key контроллера изменится, пароль root вернётся к заводскому (`wirenboard`). Кастомный SSH-ключ root'а пропадёт — ssh-copy-id заново.

Программный путь — `/usr/bin/wb-factoryreset`:

1. **Бэкап обязателен**: вызови `/controller-backup` целиком, скачай архив локально. После reset ничего не восстановишь без него. **`/mnt/data/` стирается полностью** — включая `/mnt/data/ai/` (snapshots, diag-логи, бэкапы). Скачай всё нужное локально до reset.

2. **Подтверждение пользователя** — явно перепроверь со ссылкой на потерю данных и SSH-ключа. Не запускай по неоднозначной формулировке («очисти контроллер», «сброс»).

3. **Запуск**:
   ```bash
   ssh root@<HOST> '/usr/bin/wb-factoryreset --force'
   ```
   Скрипт без `--force` интерактивно требует ввести `factoryreset` — `--force` пропускает запрос. Внутри он:
   - проверяет `firmware-compatible: fit-factory-reset` (поддерживает ли прошивка),
   - создаёт флаг `/mnt/data/.wb-update/wb_use_factory_fit.flag`,
   - ждёт ~60 сек, пока `wb-watch-update` инициирует FIT-прошивку из `/mnt/data/.wb-restore/factoryreset.fit` и reboot.

4. **SSH-сессия отвалится** во время прошивки. Контроллер недоступен 2-5 минут.

5. **После загрузки** контроллер в заводском состоянии. Hostname прежний (зависит от SN), но host-key новый. Пароль root — `wirenboard`. Авторизация снова по паролю — раздай ключ через `ssh-copy-id` если нужно.

6. **Восстановление** — по `RESTORE.md` из бэкапа (`/controller-backup` сценарий восстановления).

**Если прошивка не поддерживает factory reset** — `wb-factoryreset` ругнётся «not supported by this firmware». Это старая прошивка, factory reset делается только перепрошивкой через web UI / Recovery USB.

## Грабли

- **`apt-get update`** идёт 2-5 секунд (только обновление индексов) — синхронно через ssh ОК. **`apt-get upgrade` / `dist-upgrade` / `wb-release -t`** — долгие, через `systemd-run --collect`. Не путай.
- `wb-release -t` без `-y` — повиснет в ожидании stdin.
- Не бэкапить перед сменой релиза — кастомные конфиги могут сломаться.
- Reboot в середине `apt upgrade` — сломает dpkg.
- После смены релиза не проверить `systemctl --failed`.
- Молча проигнорировать мажорный апгрейд (Docker, containerd, u-boot, linux-image) — по ломающим изменениям пользователь должен решать сам.
- Не учесть multiarch — `apt list --upgradable | wc -l` посчитает arm64 и armhf-варианты одного пакета как два. Используй `sort -u` (см. recon).

## Документация

- Релизы: <https://github.com/wirenboard/wb-releases/blob/master/README.md>
- Wiki: <https://wirenboard.com/wiki/WB_Software_Releases>
- Update: <https://wirenboard.com/wiki/Wirenboard_Update>
