# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Что это

Интеграция Claude Code и opencode с контроллерами [Wiren Board](https://wirenboard.com). Три части:

- `mcp-server/` — MCP-сервер (TypeScript на Bun) с 43 типизированными инструментами для управления WB по SSH/MQTT.
- `skills/bash/` — 21 скилл с Bash-рецептами (SSH + `mosquitto_*` + `avahi-browse`), работают без MCP.
- `skills/mcp/` — 19 тонких скиллов, маршрутизирующих интенты на `wb_*` tools MCP-сервера.

Все части — клиентские: целевой контроллер всегда удалённый (`ssh root@wirenboard-<SN>.local`, пароль `wirenboard` по умолчанию). В этом репозитории нет кода, который выполняется *на* контроллере.

`skills/bash/` — источник доменных знаний (синтаксис wb-rules, форматы RPC, грабли Modbus). MCP-варианты ссылаются на bash для глубоких деталей и не дублируют их. Один и тот же `name:` во frontmatter — у обоих наборов; пользователь подключает ровно один.

## mcp-server — команды

```bash
cd mcp-server
bun install
bun run src/index.ts        # запуск (через stdio transport)
bun --watch run src/index.ts # dev с авторестартом
```

Тестов и линтера нет. Сборки нет — Bun исполняет TypeScript напрямую (`noEmit: true` в `tsconfig.json`).

Подключение к Claude Code — через `.mcp.json` (см. `mcp-server/.mcp.json.example`) или `claude mcp add wiren-board -- bun run /abs/path/mcp-server/src/index.ts`.

## mcp-server — архитектура

`src/index.ts` — единственная точка входа. Создаёт два singleton-объекта (`SshPool` из `lib/ssh.ts`, `Discovery` из `lib/discovery.ts`), упаковывает их в `Ctx` (см. `src/helpers.ts:5`) и поочерёдно вызывает 11 регистраторов: `registerDiscoveryTools`, `registerSshTools`, `registerJobTools`, `registerMqttTools`, `registerDeviceTools`, `registerConfigTools`, `registerRulesTools`, `registerHistoryTools`, `registerAuditTools`, `registerSerialTools`, `registerDiagnosticTools`. Каждый регистратор живёт в `src/tools/<group>.ts` и добавляет инструменты в `McpServer` через `server.registerTool(name, {description, inputSchema}, handler)`.

**Самодостаточная реализация в `mcp-server/src/lib/`:**
- `types.ts` — `Controller`, `ExecResult`, `parseSn`, `defaultHost`, `isUsableAddress`.
- `store.ts` — JSON-файл `~/.wb-mcp/controllers.json` для ручных контроллеров (без SQLite).
- `discovery.ts` — `avahi-browse -arp` + `dns.lookup`, мерж адресов, отсев IPv6 link-local.
- `ssh.ts` — обёртка над системным `ssh`/`sshpass`/`mosquitto_*`/`systemd-run` (без npm-биндингов).
- `audit.ts` — `runAudit`, `runSnapshot`, `runDiffSnapshot` для wb_audit/state-tools.

Никаких внешних зависимостей кроме `@modelcontextprotocol/sdk`, `zod` и `@types/bun`. Бинарники `ssh`, `sshpass`, `avahi-browse`, `mosquitto_sub`/`mosquitto_pub` нужны на хосте, где запускается MCP-сервер (любой Linux). Контроллеру ничего не нужно — только штатный sshd и mosquitto.

**Соглашения для новых инструментов:**

- Параметр серийника: `sn: SN` из `helpers.ts` (zod-schema, описание уже задано).
- Получить контроллер по SN: `resolveController(ctx, sn)` — бросает понятную ошибку, если не найден.
- Возвращай результат через `text(data)` (строка или JSON будет сериализован) или `err(msg)` для ошибки. Не возвращай голые объекты MCP.
- Длинные операции (`apt`, `docker run/pull/build`, `wb-release -t/-y`) определяются регексом `LONG_COMMANDS_RE` в `helpers.ts:27` — используются для маршрутизации в фоновые задачи (`wb_ssh_exec_async`).
- Описания инструментов и сообщения об ошибках — на русском (соответствует существующему стилю).

43 инструмента в 11 группах: discovery (3) · ssh+files (4) · jobs (3) · mqtt (4) · mqtt-devices (3) · confed (2) · wb-rules (5) · history (2) · audit/state (3) · modbus/serial (7) · diagnostics (7). Полная таблица — в `mcp-server/README.md`.

## Переменные окружения mcp-server

| Переменная | Default | Назначение |
|------------|---------|------------|
| `WB_SSH_USER` | `root` | SSH-логин |
| `WB_SSH_PASSWORD` | `wirenboard` | SSH-пароль |
| `WB_SSH_KEY` | — | путь к приватному ключу (альтернатива паролю) |
| `WB_DISCOVERY_INTERVAL` | `15000` | период mDNS-сканирования, мс |

## skills — структура

Каждый скилл — папка `skills/<flavor>/<name>/SKILL.md` с YAML-frontmatter (`name`, `description`, `allowed-tools`). `flavor` — `bash` или `mcp`. Корневой `wiren-board` — мастер-скилл, его описание просит подгружать при любой работе с WB. Имена внутри одинаковые в обоих наборах: один и тот же `/wb-rules` означает либо bash-, либо mcp-вариант — в зависимости от того, какой набор подключён.

**Установка** — через `./install-skills.sh <bash|mcp> <claude|opencode> [--global]`. Для Claude Code — симлинки на директории. Для opencode — конвертация frontmatter (`name` уходит в имя файла, `allowed-tools` отбрасывается, добавляется `mode: primary`) и плоские `.md` в `.opencode/agents/`. Скрипт — единственный поддерживаемый способ установки; ручная копия рискует разъехаться с конвертером.

Скиллов в `bash/` — 21, в `mcp/` — 19 (нет `diagrams` и `documentation-search`: они не зависят от контроллера, MCP не добавляет ценности — пользователь берёт их из `bash/` независимо от того, есть ли MCP).

При правке skills сохраняй существующий стиль: русскоязычные описания, серийник `A25NDEMJ` (8 символов). MCP-варианты — короткие (~30-50 строк), с таблицей «намерение → tool» и ссылкой на bash-двойник. Bash-варианты содержат полную доменную логику; самый объёмный — `wb-rules/SKILL.md` (635 строк, ES5-подмножество, `defineRule`, виртуальные устройства).

## Согласованность mcp-server ↔ skills

При добавлении нового MCP-tool в `mcp-server/src/tools/<group>.ts` обнови соответствующий `skills/mcp/<name>/SKILL.md` (таблицу маршрутизации). Если меняется доменная логика (новый формат RPC, новый шаблон Modbus) — поправь `skills/bash/<name>/SKILL.md`, на который ссылается mcp-вариант. Иначе наборы разойдутся.
