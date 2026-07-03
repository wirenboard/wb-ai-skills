# wb-ai-skills

[![CI](https://github.com/wirenboard/wb-ai-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/wirenboard/wb-ai-skills/actions/workflows/ci.yml)

*[English](README.md) · Русский*

Две вещи в одном репозитории, обе созданы, чтобы помочь ИИ-агентам-кодерам работать с контроллером [Wiren Board](https://wirenboard.com):

1. **Плагин `wb-plc`** — методологические скиллы для ИИ-агентов, управляющих контроллером по SSH. Распространяется как плагин для Claude Code / GitHub Copilot CLI и как обычный markdown для любого другого агента. См. раздел [Скиллы](#скиллы) ниже.
2. **Пакет `wb-cli`** — Debian-пакет, устанавливаемый *на* контроллер. CLI со стабильным контрактом JSON-конверта, сделанный так, чтобы агент мог зайти по SSH и вызвать `wb-cli --json <команда>`, получив структурированный вывод. См. раздел [wb-cli](#wb-cli) ниже.

Эти две части независимы: можно пользоваться скиллами без пакета на контроллере и наоборот.

---

## Скиллы

Каталог `wb-plc/skills/` содержит одиннадцать скиллов, покрывающих всё, что нужно удалённому агенту для управления контроллером WB: обнаружение, диагностику, расследование причин, сеть, MQTT, Modbus, MOD-слоты, правила автоматизации, Zigbee, резервное копирование/восстановление и написание собственного ПО для контроллера.

| Скилл | Что покрывает |
|---|---|
| `wiren-board` | Главная точка входа: обнаружение через mDNS, соглашения по SSH, использование `wb-cli`. **Загружать первым.** |
| `wb-troubleshooting` | Упавшие systemd-юниты, диск, рассогласование ядра/прошивки, Docker, диагностический архив. |
| `wb-rca` | Расследование полевых проблем и регрессий — воспроизвести, заземлить утверждения, A/B версий, доказать, оформить багрепорт. |
| `wb-serial` | RS-485 / Modbus — кастомные шаблоны, настройка устройств, диагностика шины (CRC, таймауты). |
| `wb-mod-slots` | Переконфигурация MOD-слотов WB (UART / I2C / CAN / SPI / 1-Wire) через `wb-hwconf-helper` и оверлеи device-tree. |
| `wb-rules` | Автоматизация на wb-rules JavaScript (ES5, виртуальные устройства, cron, датчики). |
| `wb-mqtt-broker` | MQTT-брокер Mosquitto — аутентификация, ACL, TLS, внешние мосты. |
| `wb-network` | Ethernet, WiFi, 4G, OpenVPN, резервирование каналов, DNS, точка доступа. |
| `wb-zigbee` | Zigbee через zigbee2mqtt (сопряжение, OTA, нативно vs Docker). |
| `wb-controller-backup` | Полное резервное копирование и восстановление контроллера. |
| `wb-dev` | Написание ПО для WB — демоны, MQTT-мосты, MQTT-RPC, кросс-компиляция, сборка Debian-пакетов. |

### Установка для Claude Code или GitHub Copilot CLI (рекомендуется)

Оба агента читают один и тот же манифест плагина. Одна команда регистрирует маркетплейс, вторая ставит плагин:

```
/plugin marketplace add wirenboard/wb-ai-skills
/plugin install wb-plc@wb-ai-skills
```

Обновления: `/plugin marketplace update wb-ai-skills`, затем `/plugin update wb-plc@wb-ai-skills`.

### Установка для OpenCode, старого Claude Code или других агентов

Используйте `install-skills.sh` — он раскладывает скиллы в формат, который ожидает каждый агент.

```bash
# Claude Code (формат скилла — каталог с SKILL.md и сопутствующими файлами)
./install-skills.sh claude              # → ./.claude/skills/   (в проекте)
./install-skills.sh claude --global     # → ~/.claude/skills/   (на пользователя)

# OpenCode (плоский .md на агента, frontmatter переписан: allowed-tools → mode: primary)
./install-skills.sh opencode            # → ./.opencode/agents/
./install-skills.sh opencode --global   # → ~/.config/opencode/agents/

# Любой другой агент (frontmatter обрезан до name + description)
./install-skills.sh manual --dest /path/to/agent/prompts

# Удаление
./install-skills.sh uninstall claude --global
```

`./install-skills.sh --help` выводит все флаги и значения по умолчанию.

### Установка в Windows

PowerShell — скопируйте каталоги скиллов из `wb-plc/skills/` в папку скиллов агента.

| Агент | Назначение |
|---|---|
| Claude Code (на пользователя) | `%USERPROFILE%\.claude\skills\` |
| Claude Code (в проекте) | `.claude\skills\` внутри проекта |
| OpenCode (на пользователя) | `%APPDATA%\opencode\agents\` (расплющить — извлечь SKILL.md как `<name>.md`, переписать `allowed-tools:` в `mode: primary`) |

### Установка на контроллер

`.deb` пакета `wb-cli` также кладёт markdown-файлы скиллов в `/usr/share/wb-cli/skills/`, чтобы зашедший по SSH агент мог читать их локально.

---

## wb-cli

Инструмент командной строки, работающий **на контроллере** и предоставляющий состояние и операции контроллера через стабильный JSON-контракт.

```bash
ssh root@wirenboard-A25NDEMJ wb-cli info
# serial_number   A25NDEMJ
# release_name    wb-2602
# hostname        wirenboard-A25NDEMJ
# uptime_seconds  407130.59

ssh root@wirenboard-A25NDEMJ wb-cli --json info
# → {"data": {"serial_number": "A25NDEMJ", "release_name": "wb-2602", ...}}

ssh root@wirenboard-A25NDEMJ wb-cli --json dev wb-mr6c_2/K1 1
# → {"data": {"device": "wb-mr6c_2", "control": "K1", "value": "1", "ok": true}}
```

### Команды

| Плагин | Что покрывает |
|---|---|
| `info` | Идентификация контроллера: серийный номер, релиз прошивки, ревизия платы, hostname, uptime |
| `audit` | Быстрая проверка состояния (упавшие юниты + идентификация) |
| `cloud` | Статус облачного агента Wiren Board |
| `dev` | Устройства и контролы — список, чтение, запись через форму wb-rules `<device>/<control>` |
| `mqtt` | Сырой MQTT: чтение retained, запись, список, живая подписка |
| `mqtt-debug` | Подробная трассировка PUBLISH в mosquitto |
| `confed` | Чтение и запись конфигов сервисов через wb-mqtt-confed |
| `rules` | Управление скриптами автоматизации wb-rules |
| `history` | Временные ряды из wb-mqtt-db (сырые строки) |
| `serial` | Операции RS-485 / Modbus (вкл. обновление прошивки `wb-fw`) |
| `serial-debug` | Отладочный захват драйвера RS-485 |
| `snapshot` | Снятие и сравнение небольших JSON-снимков состояния контроллера |
| `job` | Долгие команды как временные systemd-юниты |
| `plugins` | Самоинтроспекция: какие команды знает эта сборка wb-cli |

У каждого плагина есть свой `--help`:

```bash
wb-cli --help                    # верхний уровень — все плагины
wb-cli <plugin> --help           # подкоманды одного плагина
wb-cli <plugin> <action> --help  # флаги одного действия
```

### Режимы вывода

`wb-cli` по умолчанию везде выдаёт **человекочитаемый** вывод (таблицы / строки ключ-значение) — включая пайпы и SSH без TTY. JSON включается явно через `--json` или `WB_CLI_OUTPUT=json`. Спиннер / прогресс-бар в stderr рисуется для долгих вызовов только когда stderr — это TTY, поэтому JSON в stdout всегда остаётся чистым.

```bash
wb-cli --json dev               # принудительный JSON (LLM-агенты / скрипты)
WB_CLI_OUTPUT=json wb-cli info  # то же через переменную окружения
WB_CLI_NO_SPINNER=1 wb-cli ...  # заглушить спиннер независимо от режима
```

JSON-конверт — это стабильный машиночитаемый контракт:

- **Успех:** `{"data": { ... }}` — ключи `snake_case`, массивы всегда массивы.
- **Ошибка:** `{"error": {"code": "SCREAMING_SNAKE", "message": "...", "hint": "...", "details": { ... }}}`.

Коды возврата: **0** успех · **1** доменная ошибка · **2** ошибка использования · **3** ошибка окружения · **130** SIGINT. Коды ошибок стабильны между релизами.

### Установка на контроллер

Как только `wb-cli` будет опубликован в apt-репозитории Wiren Board:

```bash
apt-get update && apt-get install -y wb-cli
```

До этого — установите свежий `.deb` из [GitHub Releases](https://github.com/wirenboard/wb-ai-skills/releases/latest):

```bash
URL=$(curl -fsSL https://api.github.com/repos/wirenboard/wb-ai-skills/releases/latest \
      | grep -oE 'https://[^"]+wb-cli_[^"]+\.deb' | head -1)
curl -fsSL -o /tmp/wb-cli.deb "$URL"
apt-get install -y /tmp/wb-cli.deb     # разрешит python3-mqttrpc / python3-wb-common из репозитория wirenboard
```

`.deb` имеет `Architecture: all` и работает на любом wb6/wb7 с Debian ≥ bullseye.

---

## Архитектура

```
.claude-plugin/
  marketplace.json   манифест маркетплейса плагинов (Claude Code + Copilot CLI)
  plugin.json        манифест плагина wb-plc

wb-plc/skills/       руководства-скиллы для LLM — по каталогу на скилл, с
                     SKILL.md и опциональными references/, scripts/

wb_cli/              Python-пакет — корень argparse, плагины, lib/, commands/
  cli.py             корень argparse, лениво импортирует модуль плагина
  context.py         CliContext с ленивыми хэндлами (mqtt, rpc, systemd, ...)
  plugin.py          BasePlugin
  errors.py          коды ошибок и коды возврата
  output.py          рендеринг JSON-конверта
  _registry.py       сгенерированный список плагинов (make registry)
  lib/               хэндлы подсистем
  commands/          по плагину на группу команд

tests/               pytest с FakeContext + захваченный снимок wb7
debian/              сборка .deb (Architecture: all)
install-skills.sh    установка скиллов в ~/.claude/skills, ~/.config/opencode/agents и т.д.
.github/workflows/   CI (lint + тесты на py3.9/3.11, сборка .deb) и релиз по тегу v*
```

Состояние фоновых задач лежит в `/mnt/data/ai/wb-cli/jobs/<unit>.{sh,log,label,started}` — `wb-cli job` оборачивает `systemd-run --collect` и пишет туда логи.

## Разработка

Требуется Python 3.9 (целевая платформа контроллера). Репозиторий [wirenboard/codestyle](https://github.com/wirenboard/codestyle) подключён как git-сабмодуль.

```bash
git clone --recurse-submodules git@github.com:wirenboard/wb-ai-skills.git
python3 -m venv .venv && .venv/bin/pip install -e . -r requirements-dev.txt

make test      # pytest
make lint      # black --check + isort --check + pylint (должно быть 10.00)
make fmt       # автоформатирование
make registry  # перегенерировать wb_cli/_registry.py после добавления/удаления плагина
```

Соглашения:

- Целевой Python 3.9 — без `tomllib`, без PEP 695, без `match`.
- Двойные кавычки, длина строки 110.
- Файлы ≤ 250 строк (`max-module-lines` в pylint).
- MQTT subscribe: `mosquitto_sub -F '%t\t%p'` (разделитель TAB, никогда `-v`); парсить через `line.partition("\t")`.
- RPC: subprocess `mqtt-rpc-client -d <driver> -s <service> -m <method> -a <json>` (прямой `python3-mqttrpc` — оптимизация на будущее).

Добавляете новую команду? Положите `wb_cli/commands/<name>.py` с `PLUGIN = MyPlugin()`, запустите `make registry`, напишите тест.

## Версионирование

Репозиторий поставляет **два артефакта с двумя независимыми версиями**, потому что они развиваются с разной скоростью:

- **Версия пакета `wb-cli`** — то, что ставится на контроллер (`.deb`). Поднимается при изменениях уровня CLI: новые команды, изменения JSON-контракта, коды ошибок.
- **Версия плагина `wb-plc`** — то, что ИИ-агенты тянут из маркетплейса. Поднимается при изменениях содержимого скиллов: новые скиллы, правки контента, улучшения описаний. **Меняется чаще, чем пакет** — исправление опечатки в SKILL.md — это бамп плагина, а не пересборка `.deb`.

Оба следуют [семантическому версионированию](https://semver.org/) (`MAJOR.MINOR.PATCH`), но с правилами, специфичными для каждого потока версий.

### Версия пакета `wb-cli`

Авторитетный источник: `debian/changelog`. Зеркалится в `pyproject.toml` и `wb_cli/__init__.py` (тест в `tests/test_version.py` следит, чтобы все три совпадали).

- **PATCH** — исправление бага, внутренний рефакторинг, без изменения контракта.
- **MINOR** — новая команда, новая подкоманда, новая опция, новое поле в JSON-конверте, новый код ошибки.
- **MAJOR** — обратно несовместимое: удалённая/переименованная команда, изменённая форма JSON, изменённый/удалённый код ошибки, изменённый код возврата.

Пропускайте бамп для: правок CI, изменений только в тестах, формулировок в README, обновлений фикстур.

### Версия плагина `wb-plc`

Единственный источник: `.claude-plugin/plugin.json` (`"version": "X.Y.Z"`). Без зеркал, без синхронизации.

- **PATCH** — опечатка, уточнение, небольшая правка описания внутри существующего скилла.
- **MINOR** — добавлен новый скилл, новый раздел внутри существующего скилла, новые триггерные ключевые слова в описании.
- **MAJOR** — обратно несовместимое: скилл удалён или переименован (сломает ссылки в пользовательских промптах и документации).

Пользователи получают свежую версию автоматически через `/plugin marketplace update wb-ai-skills` — никакой церемонии с тегами/релизами для бампов плагина не требуется.

### Выпуск релиза `wb-cli`

```bash
# 1. поднять три файла синхронно, написать запись в changelog
dch -i                                          # или править debian/changelog вручную
sed -i 's/version = "[^"]\+"/version = "X.Y.Z"/' pyproject.toml
sed -i 's/__version__ = "[^"]\+"/__version__ = "X.Y.Z"/' wb_cli/__init__.py

# 2. коммит + тег + пуш
git commit -am "release X.Y.Z"
git tag -a vX.Y.Z -m "wb-cli vX.Y.Z"
git push && git push origin vX.Y.Z
```

`release.yml` проверяет, что тег совпадает с `debian/changelog`, собирает `.deb` и публикует GitHub Release с приложенным пакетом.

### Бамп плагина

Просто отредактируйте `.claude-plugin/plugin.json`:

```bash
sed -i 's/"version": "[^"]\+"/"version": "X.Y.Z"/' .claude-plugin/plugin.json
git commit -am "wb-plc X.Y.Z: <что изменилось>"
git push
```

Без тега — маркетплейс по умолчанию читает `main`, пользователи делают `/plugin marketplace update`, чтобы подхватить изменения.

## Участие в разработке

- Открывайте PR против `main`. CI (`make lint` + `make test` на Python 3.9 / 3.11, плюс сборка `.deb`) должен быть зелёным.
- Держите модули под 250 строк (`max-module-lines` в pylint).
- **Каждая новая команда или изменение поведения требует тестов.** Покрывайте успешный путь и каждый новый код ошибки. Без исключений.
- **Каждая новая команда должна быть вручную проверена на реальном контроллере** перед мержем. `ssh root@<controller> wb-cli <command>` — убедитесь, что работает от начала до конца.
- Тесты живут рядом с кодом, который они проверяют; стремитесь к одному тесту на успешный путь и одному на код ошибки.
- Добавление плагина: создайте `wb_cli/commands/<name>.py` с `PLUGIN = MyPlugin()`, запустите `make registry`, добавьте тесты, проверьте на железе, поднимите версию.
- Не вводите новый код ошибки, пока вызывающей стороне реально не нужно на него ветвиться — переиспользуйте существующие.

## Лицензия

MIT
