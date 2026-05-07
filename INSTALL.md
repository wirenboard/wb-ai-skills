# Установка wb-ai-integration

Два независимых пути установки. Выбирай **один**:

| Вариант | Когда | Что нужно |
|---|---|---|
| **bash-only** | Минимальный setup, нет Bun, не хочется поднимать MCP | Только SSH + `mosquitto_*` + `avahi-browse` + `jq` |
| **mcp-flavor** | Хочется типизированные tools, готов поставить Bun | Bun 1.3+, MCP-сервер запущен через `.mcp.json` |

**Не ставь оба сразу** — у `bash` и `mcp` совпадают `name:` во frontmatter скиллов, Claude Code/opencode выберет какой попало.

---

## bash-only setup

### 1. Зависимости на хост-машине

Linux:

```bash
sudo apt install avahi-utils mosquitto-clients sshpass jq
```

- `avahi-utils` — `avahi-browse` для mDNS-discovery контроллеров.
- `mosquitto-clients` — `mosquitto_sub`/`mosquitto_pub` для MQTT через SSH-туннель к брокеру контроллера.
- `sshpass` — если используешь пароль (`wirenboard` по умолчанию). Если SSH-ключ разложен — не нужен.
- `jq` — для bash-скиллов с парсингом JSON.

### 2. Клонирование и установка скиллов

```bash
git clone https://github.com/wirenboard/wb-ai-integration.git wb-ai-integration
cd wb-ai-integration

# Глобально для Claude Code:
./install-skills.sh bash claude --global
# → в ~/.claude/skills/

# Per-project (только в текущей директории):
./install-skills.sh bash claude
# → в ./.claude/skills/

# Для opencode:
./install-skills.sh bash opencode --global
# → в ~/.config/opencode/agents/
```

Скрипт ставит скиллы симлинками для Claude Code (свежие правки сразу видны), и плоскими `.md` для opencode (с конвертацией frontmatter).

### 3. SSH-доступ к контроллерам

По умолчанию контроллеры WB:
- **Логин**: `root`
- **Пароль**: `wirenboard` (заводской)
- **Хост**: `wirenboard-<SN>.local` (через mDNS) или прямой IP.

**Рекомендуется разложить SSH-ключ** (избегаем пароля и `sshpass`):

```bash
ssh-copy-id -o StrictHostKeyChecking=accept-new root@wirenboard-A25NDEMJ.local
```

После этого SSH работает без пароля.

### 4. Проверка

В Claude Code:

```
> /wiren-board
> найди все контроллеры в сети
```

Скилл должен сделать `avahi-browse -arp _workstation._tcp` и показать список.

---

## MCP-flavor setup

### 1. Зависимости

Те же что для bash-flavor (`avahi-utils`, `mosquitto-clients`, `sshpass`, `jq`) **плюс**:

- **Bun 1.3+** — runtime для MCP-сервера ([bun.sh](https://bun.sh)).

```bash
curl -fsSL https://bun.sh/install | bash
```

### 2. Установка MCP-сервера

```bash
git clone https://github.com/wirenboard/wb-ai-integration.git wb-ai-integration
cd wb-ai-integration/mcp-server
bun install
```

Сборки нет — Bun исполняет TypeScript напрямую. `noEmit: true` в `tsconfig.json`.

### 3. Установка MCP-скиллов

```bash
cd ..
./install-skills.sh mcp claude --global
# или
./install-skills.sh mcp opencode --global
```

### 4. Подключение MCP-сервера к Claude Code

В `~/.claude.json` (глобально) или `.mcp.json` (в проекте):

```json
{
  "mcpServers": {
    "wiren-board": {
      "command": "bun",
      "args": ["run", "/ABS/PATH/wb-ai-integration/mcp-server/src/index.ts"],
      "env": {
        "WB_SSH_USER": "root",
        "WB_SSH_PASSWORD": "wirenboard"
      }
    }
  }
}
```

Или одной командой:

```bash
claude mcp add wiren-board -- bun run /ABS/PATH/wb-ai-integration/mcp-server/src/index.ts
```

### 5. Подключение MCP-сервера к opencode

В `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "wiren-board": {
      "type": "local",
      "command": ["bun", "run", "/ABS/PATH/wb-ai-integration/mcp-server/src/index.ts"],
      "environment": {
        "WB_SSH_USER": "root",
        "WB_SSH_PASSWORD": "wirenboard"
      },
      "enabled": true
    }
  }
}
```

Различия с Claude Code:
- ключ верхнего уровня — `mcp`, не `mcpServers`;
- `command` — массив `[cmd, ...args]`, не строка + `args`;
- env — `environment`, не `env`.

### 6. Переменные окружения

| Переменная | Default | Назначение |
|------------|---------|------------|
| `WB_SSH_USER` | `root` | SSH-логин |
| `WB_SSH_PASSWORD` | `wirenboard` | SSH-пароль (если нет ключа) |
| `WB_SSH_KEY` | — | путь к приватному ключу (вместо пароля) |
| `WB_DISCOVERY_INTERVAL` | `15000` | период mDNS-сканирования (мс) |

### 7. Проверка

В Claude Code (после рестарта, чтобы подтянулся `.mcp.json`):

```
> /wiren-board
> найди контроллеры через wb_discover
```

Должны появиться записи с `sn`, `host`, `addresses`, `reachable: true`.

```
> wb_probe sn=A25NDEMJ
```

Вернёт `uname`, `release`, `fwVersion`.

---

## Типовые проблемы

### `wb_discover` ничего не находит

**Причины и проверки** (по убыванию вероятности):

1. **mDNS-кеш ещё пустой.** Первый запуск MCP-сервера — discovery опрашивает сеть каждые 15 сек. Подожди ~15 сек после старта и повтори.
2. **`avahi-daemon` не запущен на хосте.** Linux: `systemctl status avahi-daemon`. Запусти если выключен.
3. **Multicast блокирован между сегментами.** mDNS работает только в одном broadcast-домене. Если контроллер за NAT/VPN/в другой VLAN — не увидит.
4. **WB-AP режим.** Если контроллер в режиме точки доступа (`wb-ap`) и хост не подключён к нему по WiFi — не виден.

**Workaround:** `wb_add_controller host=192.168.x.y` — ручное добавление по IP, минуя mDNS.

### SSH timeout / handshake failure

1. **Контроллер только что загрузился** (uptime < 1 мин) — sshd ещё инициализирует крипто. Подожди 30-60 сек и повтори.
2. **`StrictHostKeyChecking` блокирует** (хотя у нас выключен) — если используешь bash-flavor с системным `ssh`, поправь `~/.ssh/known_hosts`: `ssh-keygen -R wirenboard-A25NDEMJ.local`. После factory reset host-key изменится.
3. **Пароль изменён** — после `factoryreset` пароль root возвращается к `wirenboard`. Если до того ставил свой — прежний WB_SSH_PASSWORD теперь не работает.

### `bun: command not found`

Bun не в `PATH`. После установки:

```bash
echo 'export BUN_INSTALL="$HOME/.bun"' >> ~/.bashrc
echo 'export PATH="$BUN_INSTALL/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Либо в `.mcp.json` укажи полный путь: `"command": "/home/<user>/.bun/bin/bun"`.

### MCP-сервер не подхватывается Claude Code

1. Перезапусти Claude Code после правки `.mcp.json` / `~/.claude.json`.
2. Проверь логи: Claude Code пишет ошибки запуска MCP в свой лог (`/help` → раздел диагностики).
3. Проверь руками: `bun run /ABS/PATH/wb-ai-integration/mcp-server/src/index.ts` — должен ничего не выводить (stdio-transport ждёт сообщения), если выводит ошибку — это и есть проблема.

### `Invalid subscription topic` в `wb_mqtt_list`

В MQTT wildcards `+`/`#` занимают **весь уровень между `/`**, не часть имени. Пример невалидного: `/devices/system__wb-cloud-agent__+/...` (`+` внутри уровня).

Корректно: `/devices/+/controls/+` или `/devices/<точное_имя>/#`.

### Контроллер не обновляется через apt

После factoryreset на старой прошивке (например wb-2410) репозиторий `deb.wirenboard.com` может временно отдавать **403** (CDN-кеш). Проверка:

```bash
ssh root@<host> 'curl -sI http://deb.wirenboard.com/wb7/bullseye/dists/stable/InRelease | head -3'
```

Если 403 — подожди 24 часа (TTL CDN) или используй `wb-release -t <свежий-релиз>` чтобы переключить репозиторий.

---

## Деинсталляция

### Bash/MCP-скиллы

Удали созданные файлы/симлинки в директории, которую `install-skills.sh` печатает в конце.

```bash
# Claude Code (global) — install-skills.sh кладёт симлинки на каталоги:
unlink ~/.claude/skills/wiren-board   # каждый по имени
# или массово:
find ~/.claude/skills -maxdepth 1 -type l -lname '*wb-ai-integration/skills/*' -delete

# opencode (global) — это плоские .md файлы:
rm ~/.config/opencode/agents/wiren-board.md   # каждый по имени
```

### MCP-сервер

```bash
# Claude Code
claude mcp remove wiren-board

# или вручную: убери блок из ~/.claude.json / .mcp.json

# Сам сервер не оставляет ничего на хосте — Bun не ставит global-биннарики.
# Удали клон проекта:
rm -rf wb-ai-integration
```

### Артефакты на контроллерах

Скиллы пишут в `/mnt/data/ai/wb-ai-integration/` (snapshots, jobs, diag, backups). Это не критично — переживёт factoryreset и не мешает работе. Чистка вручную если хочешь:

```bash
ssh root@<host> 'rm -rf /mnt/data/ai/wb-ai-integration'
```
