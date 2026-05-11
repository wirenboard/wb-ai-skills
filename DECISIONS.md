# wb-cli — design decisions

Накопительный лог решений. Источник правды — код; этот файл фиксирует **почему**, а не **что**.

## Среда

- Debian 11 bullseye на контроллере, Python 3.9.2.
- Сборка пакета в CI (bookworm/trixie), установка на bullseye.
- stdlib + apt-пакеты. Никакого pip, никакого Click.
- `Depends: python3 (>= 3.9), python3-mqttrpc, python3-wb-common, mosquitto-clients, jq`.

## Архитектура

```
cli.py / output.py / errors.py    каркас
plugin.py / context.py            BasePlugin + CliContext с lazy handles
commands/*.py                     плагины (тонкая оркестрация)
  commands/modbus/                subpackage (>4 субкоманд)
lib/*.py                          handles: controller, mqtt, rpc, shell, systemd, journal, job
```

- `cli.py`: argparse root, lazy-import плагина по `argv[1]`, dispatch, envelope.
- `context.py`: CliContext с lazy handles (создаются при первом обращении, не при каждом вызове).
- `plugin.py`: BasePlugin — единственная абстракция. Без Protocol, без версионирования.
- `_registry.py`: dict `{name: (module, help)}`, генерируется `make registry`.

## Команды (13 плагинов)

`info`, `devices`, `mqtt`, `confed`, `rules`, `history`, `modbus`, `cloud`, `serial-debug`, `audit`, `snapshot`, `job`, `plugins`.

Стандартный Linux (systemctl, journalctl, docker, apt, ip) — LLM вызывает по SSH напрямую.

## Output

- `{"data": {...}}` или `{"error": {"code": "...", "message": "...", ...}}`.
- `snake_case` ключи. Массивы всегда массивы. Timestamps ISO-8601.
- Exit codes: 0 success, 1 domain, 2 usage, 3 environment, 130 SIGINT.
- Error codes: `SCREAMING_SNAKE_CASE` с prefix-категорией. Стабильны после релиза.

## MQTT

- `mosquitto_sub -F '%t\t%p'` — TAB-separator, никогда `-v`.
- Парсинг через `line.partition("\t")`.
- Пробелы в именах controls — в фикстурах и тестах.

## RPC

Текущая реализация: subprocess `mqtt-rpc-client`. Планируется прямой импорт `python3-mqttrpc` (оба в Depends).

## Job machinery

- `/mnt/data/ai/wb-cli/jobs/<unit>.{sh,log,label,started}`.
- `systemd-run --collect` + `StandardOutput=append:<logfile>`.
- GC при `job run` — чистим старше 24ч.
- wait() поллит `systemctl is-active` каждые N секунд.

## Скиллы

10 SKILL.md в `skills/`. В .deb ставятся в `/usr/share/wb-cli/skills/`.
Для оператора: `./install-skills.sh claude --global` (symlinks в `~/.claude/commands/`).

Критерий «нужен скилл vs хватит wb-cli --help»: скилл содержит **методологию** (порядок действий, паттерны ошибок, неочевидные зависимости), а не просто команды.
