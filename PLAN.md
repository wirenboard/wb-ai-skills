# План — публикация wb-ai-integration

## Цель

Подготовить репозиторий к публикации: проверить все скиллы и MCP-сервер на живых контроллерах, починить найденное, написать недостающую документацию.

## Тестовое окружение

- **Хост:** `192.168.2.105` (текущая машина).
- **Контроллеры:**
  - `A25NDEMJ` → `wirenboard-A25NDEMJ.local` → `192.168.2.106`.
  - `A2V6W7I6` → `wirenboard-A2V6W7I6.local` → `192.168.2.123`.
- **Доступ:** ssh-ключ `~/.ssh/id_ed25519` нужно разложить (`ssh-copy-id` × 2).

## Фазы

### Фаза 0 — подготовка

- [x] Установить ssh-ключ на оба контроллера. A25NDEMJ — ключ. A2V6W7I6 — `sshpass -p wirenboard` (по соглашению с пользователем).
- [x] Проверить, что `ssh root@wirenboard-<SN>.local` уходит без интерактива.
- [x] Зафиксировать состояние A25NDEMJ: wb-2602/wb7, fw `202603181402`, релиз stable, uptime 44 дня.
- [x] Зафиксировать состояние A2V6W7I6: wb-2507/wb8, fw `202505010753`, релиз stable, uptime 83 дня.
- [x] Бэкап A2V6W7I6: `/tmp/wb-baselines/A2V6W7I6-baseline-20260507.tar.gz` (12 МБ; собран при тестировании скилла `controller-backup`).
- [ ] Бэкап A25NDEMJ — пока не делал; сделать перед первым деструктивным тестом на нём.

### Фаза 1 — bash-скиллы без MCP

Цель: проверить, что доменные знания в `skills/bash/<name>/SKILL.md` корректны и приводят к ожидаемому результату на живом железе. Скилл считается готовым, когда модель, читая только `SKILL.md`, успешно делает реальную задачу.

Каждая задача — на одном из контроллеров. По возможности — на обоих, чтобы поймать device-specific странности.

#### Проверка по скиллам

| Skill | Проверочный сценарий | Статус | Что найдено |
|-------|---------------------|--------|-------------|
| `wiren-board` (мастер) | Discovery → ssh → fw + uptime + список сервисов | [x] | Все 5 пунктов прошли. Поправлено: `head -5 /usr/lib/wb-release` → `grep -E ...` или `cat` (магическое число обещало 3 поля, обрезало мусор) |
| `wb-mqtt-serial` | На A25NDEMJ: найти WB-устройство, включить отключённый канал (например `Uptime`), убедиться что значение публикуется | [x] | Включён `Uptime` на `wb-mr6c_2`, виден в MQTT, откатано к исходному. Найдено 3 критичных бага (LoadConfig без channels, GetTemplate timeout, content as string ломает шину). См. журнал. |
| `wb-rules` | На A25NDEMJ: создать правило, которое логирует изменение какого-то контрола; проверить что reload прошёл; удалить | [x] | Создано+проверено+удалено `wb-la-test-ai-validate.js` на hwmon/CPU Temperature, 3 срабатывания в логах, без ошибок ES5. Поправлено: примечание про отсутствие `Editor/Remove` RPC, диагностика пустого `meta/type`, безопасная иерархия Save-примеров (jq -Rs основной, printf "%s" с предупреждением). Также чищу `wb_rules_delete` MCP-tool (был try-catch с заведомо ломающимся RPC, теперь сразу rm+restart). |
| `troubleshooting` | Диагностический проход на A25NDEMJ: kernel mismatch, диск, failed-сервисы, журнал ошибок, нагрузка. Найти и объяснить настоящий failed unit. | [x] | На контроллере живо упал `fstrim.service` (status=64/USAGE — `/mnt/sdcard` в fstab без вставленной SD). Поправлено: `journalctl -p err` без `--since` показан как баг (надо `--since '1 hour ago'`); добавлен `systemctl status <unit>` рядом с `journalctl -u`; добавлен паттерн fstrim/USAGE в таблицу типичных проблем; порог места заменён с абсолютного «100 МБ» на процентный. Те же фиксы — в MCP-двойнике. |
| `troubleshooting-serial` | На A25NDEMJ: запустить serial-debug-сессию, проверить что debug включился/выключился, лог собрался | [x] | Полный проход: histogram, debug 120s, scan, probe, modbus_client_rpc по 3 устройствам. На контроллере: 4 транзиентных ошибки за час (slaves 19, 201), debug-окно чистое, scan нашёл 7 из 8 устройств (MAP6S слот 34 пропущен — проверен Probe'ом, живой). Поправлено 6 серьёзных багов в скилле + tool. Главное: рецепт debug-сбора оставлял `journalctl -n 500` (молча резал длинные окна), не имел `trap` (висший рестарт оставлял debug=true), regex sed мутил пробелы; добавлен trap-обвязанный скрипт, абсолютный START_TS, проверка состояния после, явное обновление стейта. Вторичное: `templates/GetTemplate` ушёл в пользу чтения файла, гистограмма по slave-id дополнена сырыми последними строками (regex пропускал шумные ошибки), правка про регистры 121-122 (не универсальны), про scan-miss WB-MAP6S, про `ports/Load`=активные а не все. Те же фиксы в `wb_serial_debug` MCP-tool и MCP-двойнике скилла. |
| `controller-backup` | Полный цикл на A2V6W7I6: аудит, фазы 2+3, скачать архив, прочитать RESTORE.md | [x] | Прошло. Архив 12 МБ, скачан как `/tmp/wb-baselines/A2V6W7I6-baseline-20260507.tar.gz` (одновременно служит baseline-снимком A2V6W7I6 для Фазы 0). Найдено 4 правки: (1) аудит mntdata не видел скрытые каталоги (`.dockge` с compose stacks Dockge пропускался) — исправлен `shopt -s dotglob`; (2) чеклист не упоминал шаг 1b (snapshot) — добавлен; (3) Docker-восстановление подразумевало `wb-docker-manager.sh` как обязательный путь, на этом контроллере его нет — добавлен fallback на `apt install docker-ce containerd.io docker-ce-cli`; (4) добавлено уточнение что core-tar включает `mnt/data/etc` рекурсивно (то есть `/mnt/data/etc/docker/` и симлинки конфигов уже там, не дублируй в audit-files). Те же фиксы — в `lib/audit.ts` MCP-сервера. |
| `controller-update` | Только recon-команды на обоих (без реального upgrade) | [x] | A25NDEMJ: 38 upgradable, нет linux-image — reboot не нужен. A2V6W7I6: 95 upgradable + смена ядра 6.8.0-wb140→wb153 + мажорный Docker (28→29, containerd 1→2). Поправлено: (1) recon шаг 1 теперь делает kernel-mismatch проверку (мастер-скилл считает её первой при проблемах после обновления — а перед обновлением её делать ещё важнее); (2) добавлены пороги свободного места (`>=1 ГБ` норма, `<500 МБ` критично); (3) `apt-get update` через синхронный ssh — ОК (2-5 сек), уточнено в Граблях; (4) добавлен раздел про мажорные апгрейды (Docker/containerd/u-boot/linux-image) и подсчёт `apt list --upgradable` с `sort -u` для multiarch. Те же правки — в MCP-двойнике. |
| `hardware-modules` | Прочитать `/etc/wb-hardware.conf` через RPC, не менять | [x] | На A2V6W7I6 (wb8) реальные слоты: `wb84-mod1..3` (3 шт., не 4; mod1 без UART), 2× `wb84-rs485-*`, 8× `wb84-extio*`, `wb84-w1/w2`, `wb84-wbmz5`, `wb72-wbc`. Найдено: (1) скилл утверждал «mod1-4», на wb8 их 3 + некоторые без UART; (2) module-IDs в таблице (`wbe2-i-zigbee/can/rs485`) **не существуют** в реальной schema — реальные `wbe2r-r-zigbee`, `wb67-can-rs485`, `wbe2-i-rs232` (последний совпал, остальные нет); (3) слоты W1/W2/WBMZ5/модем были не упомянуты вовсе; (4) проверка `ls /dev/ttyMOD<N>` ложно-негативна для не-UART модулей (1-Wire, extio, GPIO) — не путай с ошибкой установки. Все 4 правки внесены в bash и MCP-скиллы. |
| `software-install` | На A25NDEMJ установить Node-RED (apt+npm, реальная установка) | [x] | Установлено, http://wirenboard-A25NDEMJ.local:1880/ работает. Скилл имел дыру: `description` обещал Node-RED, в теле — только Docker и Z2M. Добавлен полный раздел Node-RED (apt deps, симлинк `~/.node-red→/mnt/data/`, npm install через systemd-run, systemd-unit, проверка, предупреждение про отсутствие auth). Поправлено: rootfs-инфо стала точнее (физически 2 ГБ, реально доступно ~1.2 ГБ); проверка «уже установлено?» дополнена случаями npm-глобалок и контейнеров (раньше только `dpkg -l | grep` — для Node-RED ничего не покажет); явно сказано что `npm install -g` тоже долгая, через `systemd-run`. Те же фиксы — в MCP-двойнике. |
| `zigbee` | Если есть Zigbee-модуль: прочитать `bridge/state`, список устройств | [x] | На A2V6W7I6 Z2M в **Docker** (контейнер up 2 мес.), 6 устройств: Aqara wireless mini switch, WBMSW4, eWeLink ZB-SW01, Aqara water leak, SONOFF SNZB-01P, BITUO TECHNIK SPM01X. Конвертер — старый `wb-zigbee2mqtt 1.4.1` (как wb-rules-скрипт), устройства публикуются под `/devices/0x<ieee>` (не `zigbee_<id>`!). Найдено 5 правок: (1) Z2M в Docker → `systemctl is-active`=inactive когда мост работает; единственно правильный probe — `bridge/state` через MQTT. (2) Архитектурная таблица перепутана: префикс `zigbee_*` — только у нового конвертера, старый даёт `0x<ieee>`. (3) `head -c 200` для `bridge/devices` даёт битый JSON — заменено на полный забор + `jq`. (4) `last_seen` per-device есть только при `availability.enabled: true` — иначе отсутствие поля не значит офлайн. (5) `permit_join` сразу без предупреждения о деструктивности — добавлено явное предупреждение. Те же фиксы — в MCP-двойнике. |
| `history` | Запросить историю CPU Temperature за час | [x] | На A25NDEMJ live: 53 бакета за час (CPU Temp + Board Temp), max=80.12°C, value=78.40°C — пик в 17:31. Найдено 7 правок: (1) Шаг 1 не давал способа узнать имена контролов через `meta/name` — заменено на `mosquitto_sub -v -t '/devices/+/controls/+'`. (2) Старый пример RPC ломался по экранированию `$(...)` через `ssh ... bash -c '...'` — заменён на `ssh ... 'bash -s' <<'EOF'` (heredoc на удалённой стороне). (3) Структура ответа была не описана: каждая точка — **бакет** с `value` (сглаженное среднее), `min`, `max`. Для пиков смотри `max`, не `value`. (4) `min_interval=0` ≠ «все сырые точки» — сервер всё равно агрегирует ~120с. (5) Multi-channel вынесен в основной пример (3 канала за один RPC), `limit` per-channel не суммарный — добавлено в Грабли. (6) `apt install wb-mqtt-db` если inactive — теперь через `/software-install` с согласованием. (7) Грабля «разные единицы на одном графике — бессмысленно» **была неверна**: пользователь указал на `wb-ai-helper-desktop/src/server/history-chart.ts` — там продуманный multi-axis-рендер (1 unit → одна шкала, 2 → двойная ось через `resolve.scale.y: independent`, 3+ → нормализация). Раздел переписан как «Визуализация: разные единицы», добавлены варианты рендера (Mermaid `xychart-beta` для одной серии, Python+matplotlib, AI Helper). Проверено live, рецепт в скилле работает первой попытки. Те же фиксы — в MCP-двойнике. |
| `bugreport` | Собрать diag-архив на A25NDEMJ, скачать | [x] | На A25NDEMJ выполнен полный цикл по `fstrim.service status=64/USAGE` — до диагноза «`/etc/fstab` ссылается на `/mnt/sdcard` без вставленной SD; `fstrim --listed-in` обходит fstab без учёта `nofail`», собран diag-архив 384 КБ, оформлен багрепорт. Найдено 8 правок: (1) `wb-diag-collect` принимает **префикс**, не каталог — было неочевидно из рецепта (написано как `<dir>`); архив имеет вид `diag_<SN>_<TS>.zip`. (2) `scp ...:diag*.zip ./` развернёт глоб на удалённой стороне → скачает все старые архивы; нужен `LATEST=$(ssh...); scp ...:"$LATEST"`. (3) Команда снимка состояния не сохранялась в файл — добавлен `tee`. (4) Cross-references на `/troubleshooting`, `/troubleshooting-serial`, `/controller-backup`, `/controller-update`, `/wiren-board` отсутствовали — добавлены. (5) Шаблон багрепорта расширен (severity, что уже пробовали, желательный исход, контактный канал — реально часто запрашиваемые поля поддержки). (6) Принцип «минимум спрашивай» противоречил списку из шага 4 — уточнено, что список запасной. (7) Уточнено, когда diag-архив **не нужен** (упавший systemd-юнит = `journalctl + status + cat`). (8) Реальный анализ архива на 159 файлов показал, что **не покрыты не-WB юниты** (`fstrim.service`, кастомные), логи Docker-контейнеров, долгопериодные выборки, MQTT-состояние — добавлен раздел «что есть/чего нет» + рецепты прицельного сбора (`journalctl -u <non-wb-unit>`, `docker logs`, `journalctl -p err --since 7d`). Это критично — наш собственный кейс (fstrim) не отразился бы в архиве, и без явного `journalctl -u fstrim.service` в багрепорте поддержка не увидела бы причину. Те же правки в MCP-двойнике. |
| `diagrams` | Сгенерировать пример Mermaid-диаграммы по реальному правилу | [x] | На A25NDEMJ для правила `wb-la-temp-relay.js` (гистерезис 49-50°C) построены: таблица каналов, таблица состояний с dead-zone, `stateDiagram-v2` (с hold-состоянием) + `flowchart TD` обработчика. Найдено 4 правки: (1) Таблица выбора типа односложна — для гистерезиса/sticky нужны **обе** диаграммы (state+flowchart) или + Markdown-таблица; добавлены строки. (2) Скилл написан под design (новое правило); reverse-engineering (анализ существующего, как в этой задаче) не упомянут — добавлены два режима. (3) Образец «Таблицы каналов» отсутствовал, упоминался только в формате ответа — добавлен пример. (4) В примере flowchart `\n` рендерится как литерал, нужно `<br/>` — поправлено + явное предупреждение. **Дополнительно:** `install-skills.sh` теперь при flavor=mcp автоматически подтягивает `diagrams` и `documentation-search` из bash/ — иначе cross-references из MCP-скиллов на эти два скилла были бы мёртвыми (в `mcp/` их нет). |
| `documentation-search` | Найти страницу по WB-MR6C, процитировать URL | [x] | Реальный поиск по «WB-MR6C broadcast» дал 5 находок с 7 URL вики/GitHub. Скилл переписан по 6 находкам субагента + директива пользователя «искать через поисковики, не через `Special:Search`». Главные правки: (1) **Домен `wirenboard.com/wiki/...` 301-редиректит** на `wiki.wirenboard.com/wiki/...` — все примеры в скилле были на старый, каждый вызов терял раунд-трип; теперь явно `wiki.wirenboard.com` + грабля. (2) **`Special:Search` слабее Google** на русских запросах — теперь основной путь `WebSearch 'site:wiki.wirenboard.com ...'`, прямой `WebFetch` — для известных URL. (3) **Несуществующий пример** `raw.githubusercontent.com/.../config-wb-mr6c.json` (404) — заменён на API-листинг через `curl/gh api`. (4) **Страницы `github.com/.../tree/...`** — JS-SPA, не парсятся; убрано из примеров. (5) Совет «raw `main` vs `master`» добавлен (часть репо WB на master). (6) Лимиты WebSearch уточнены (2-3 на тему, не 3 на ответ). |

#### Методика проверки

1. Для каждого скилла:
   - Сформулировать конкретную пользовательскую задачу.
   - В чистой сессии Claude Code прочитать SKILL.md и попробовать решить задачу.
   - Записать что не сработало (неясный шаг, неверная команда, отсутствующая деталь).
   - Поправить SKILL.md, повторить.
2. После прохода — отметить статус, в колонке «что найдено» записать суть багов и ссылок на коммиты с фиксами.

### Фаза 2 — MCP-сервер и MCP-скиллы

Цель: проверить, что `wb_*` tools работают с реальными контроллерами и MCP-скиллы корректно их используют.

#### 2a. Сам MCP-сервер

- [x] Запустить `cd mcp-server && bun run src/index.ts` локально, проверить что стартует без ошибок.
- [x] Подключить к Claude Code через `.mcp.json` (см. README).
- [x] Прогнать каждый из 37 tools хотя бы один раз на живых контроллерах (2026-05-07, A25NDEMJ + A2V6W7I6; нашли 7 багов, исправлены — нужен рестарт MCP для активации фиксов):
  - [x] discovery (3): `wb_discover`, `wb_probe`, `wb_add_controller`
  - [x] ssh+files (4): `wb_ssh_exec`, `wb_ssh_exec_async`, `wb_read_file`, `wb_write_file`
  - [x] jobs (3): `wb_job_status`, `wb_job_tail`, `wb_job_cancel` — баг в job log redirect, фикс готов
  - [x] mqtt (4): `wb_mqtt_read`, `wb_mqtt_write`, `wb_mqtt_list`, `wb_mqtt_rpc`
  - [x] mqtt-devices (2): `wb_mqtt_devices`, `wb_mqtt_controls` — баг парсера, фикс готов
  - [x] confed (2): `wb_confed_load`, `wb_confed_save` — fool-proof для строки в content, фикс готов
  - [x] rules (5): `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_delete`, `wb_rules_disable` — баг path в save/load, фикс готов
  - [x] history (2): `wb_history`, `wb_history_chart` — оба ОК
  - [x] audit/state (3): `wb_audit`, `wb_state_save`, `wb_state_diff` — баг парсера секций, фикс готов
  - [x] modbus (6): `wb_modbus_template`, `wb_modbus_templates_list` (новый), `wb_modbus_channels`, `wb_modbus_probe`, `wb_modbus_ports`, `wb_modbus_scan` — template и scan: фиксы готовы
  - [x] diagnostics (4): `wb_metrics`, `wb_logs`, `wb_failed`, `wb_serial_debug` (последний — журнал фазы 1)
- [ ] Проверить устойчивость к разрыву SSH (`wb_ssh_exec_async` должен переживать) — после рестарта MCP с фиксом log redirect.
- [x] Проверить параллельные вызовы (несколько tools одновременно по разным контроллерам) — wb_probe + wb_metrics на A25NDEMJ + A2V6W7I6 параллельно ОК.

#### 2b. MCP-скиллы

Та же таблица из фазы 1, но через MCP. Для каждого: должна получиться **та же задача за меньшее число шагов** и без `ssh`/`mosquitto_*` руками.

| Skill | Сценарий | Статус | Замечания |
|-------|---------|--------|-----------|
| `wiren-board` (mcp) | wb_discover → wb_probe → wb_metrics на обоих | [ ] | |
| `wb-mqtt-serial` (mcp) | Тот же канал, что в фазе 1, через `wb_modbus_*` + `wb_confed_*` | [ ] | |
| `wb-rules` (mcp) | То же правило через `wb_rules_save` | [ ] | |
| `troubleshooting` (mcp) | Тот же сценарий через `wb_failed`/`wb_logs`/`wb_metrics` | [ ] | |
| `troubleshooting-serial` (mcp) | Через `wb_serial_debug` (один tool вместо длинного скрипта) | [ ] | Главный тест: tool правда сам всё делает? |
| `controller-backup` (mcp) | Через `wb_audit` + `wb_state_save` + `wb_ssh_exec_async` | [ ] | |
| `controller-update` (mcp) | Recon через `wb_probe`/`wb_metrics`/`wb_ssh_exec` | [ ] | |
| `hardware-modules` (mcp) | `wb_confed_load /etc/wb-hardware.conf` | [ ] | |
| `software-install` (mcp) | До подтверждения установки через `wb_ssh_exec_async` | [ ] | |
| `zigbee` (mcp) | Через `wb_mqtt_read zigbee2mqtt/...` | [ ] | |
| `history` (mcp) | `wb_history` за час | [ ] | |
| `bugreport` (mcp) | Через `wb_audit` + `wb_state_save` + `wb_ssh_exec_async wb-diag-collect` | [ ] | |

#### 2c. opencode

- [ ] Установить opencode (если ещё нет).
- [ ] Прогнать `./install-skills.sh mcp opencode --global`, проверить что 12 файлов на месте.
- [ ] Подключить MCP-сервер через `opencode.json` по примеру из README.
- [ ] Прогнать 2-3 базовых сценария (`wb_discover`, `wb_metrics`, `wb_logs`) — убедиться что вызовы из opencode действительно ходят в наш сервер.

### Фаза 3 — документация

#### Что точно нужно

- [ ] **README.md** — пройтись свежим взглядом: ничего не устарело после правок, шаги установки воспроизводятся с нуля.
- [ ] **mcp-server/README.md** — обновить, если в фазе 2 появились новые env vars / настройки.
- [ ] **Новый файл `INSTALL.md`** или раздел в README:
  - Установка bash-flavor — для пользователей Claude Code/opencode без MCP-сервера. Минимально достаточно SSH-доступа и avahi.
  - Установка mcp-flavor — bun, mcp-server, конфиг, проверка работоспособности.
  - Типовые проблемы (mDNS не работает, ssh ключ не разложен, bun не установлен).
- [ ] **`CHANGELOG.md`** или вкладыш в README — что в каком релизе.
- [ ] **`LICENSE`** — выбрать (вероятно MIT или Apache 2.0, согласовать).

#### Что хорошо бы

- [ ] Короткое демо в README (gif или текстовая запись сессии «нашёл контроллер → включил канал → создал правило»).
- [ ] Список «известные ограничения» (то, что MCP не покрывает: scp каталогов, Docker registry login и т.п.).
- [ ] Примеры реальных задач — отдельная папка `examples/` с записями сессий.

### Фаза 4 — публикация

- [ ] Создать публичный git-репозиторий (GitHub под организацией Wiren Board или личный).
- [ ] Перенести историю с правильным `.gitignore` (исключить `node_modules/`, `bun.lock` оставить).
- [ ] Тег `v0.1.0`, выпустить release с changelog.
- [ ] Анонс там, где аудитория Wiren Board (форум, телеграм-чат).

## Порядок работы

1. Сначала фаза 0 (подготовка) — иначе нечем тестировать.
2. Фаза 1 проходим по таблице сверху вниз. Каждый скилл — отдельная итерация: задача → проверка → правка → отметка.
3. Перед фазой 2 — поднять MCP-сервер локально и убедиться, что он стартует.
4. Фаза 2 идёт по той же логике.
5. Фаза 3 — после того, как все скиллы прошли проверку (иначе документация устареет в процессе).
6. Фаза 4 — финальный шаг.

## Критерии готовности

- Все галочки в фазах 1-3 закрыты.
- Свежая сессия Claude Code, прочитав только `README.md` + установив bash-скиллы, может решить базовую задачу (discover + ssh + read state) на A25NDEMJ.
- То же — с MCP-flavor: прочитав README, установив сервер и MCP-скиллы, новая сессия делает ту же задачу через `wb_*`.
- Опубликованный репозиторий клонируется и устанавливается с нуля по инструкциям без подсказок «спросите у Андрея».

## Журнал найденного

Сюда — короткие пометки во время прохода, с датой и ссылкой на коммит/PR с фиксом.

- 2026-05-07 — bash mDNS recipe искал `_http._tcp`, контроллеры публикуют `_workstation._tcp`. Пайп `timeout | awk` терял строки. Discovery class перезаписывал addresses. См. предыдущие правки.
- 2026-05-07 — путь к SN: было `/var/lib/wirenboard/short_sn`, реально `/var/lib/wirenboard/short_sn.conf`. Поправлено в `skills/bash/wiren-board/SKILL.md`, `skills/bash/bugreport/SKILL.md`, `skills/mcp/wiren-board/SKILL.md`, `wb-ai-helper-desktop/src/server/fixtures/skills/bugreport.md`. Альтернатива через MQTT: `/devices/system/controls/Short SN`.
- 2026-05-07 — mDNS-кеш истекает per-name: `ssh root@wirenboard-XXX.local` может упасть с `Could not resolve hostname` при том, что `ping` той же команды выше резолвит. Лекарство — прогон discovery перед серией SSH или работа по IP. Описано в bash master-skill.
- 2026-05-07 — добавлен раздел про `sshpass` для Linux-хостов в `skills/bash/wiren-board/SKILL.md` (когда ключ разложить нельзя). Замена `StrictHostKeyChecking=no` на `accept-new`.
- 2026-05-07 — `head -5 /usr/lib/wb-release` в скилле `wiren-board` обещало 3 поля (RELEASE_NAME/SUITE/TARGET), но `-5` не привязано к их позициям и режет файл произвольно. Заменено на `grep -E '^(RELEASE_NAME|SUITE|TARGET)=' /usr/lib/wb-release` + альтернатива `cat` для полного содержимого.
- 2026-05-07 — `mcp-server` структурно зависел от соседнего репо `wb-ai-helper-desktop` через `../../../src/server/...`. Для самостоятельной публикации это блокер. Реализованы СОБСТВЕННЫЕ копии в `mcp-server/src/lib/`: `types.ts`, `store.ts` (JSON вместо SQLite), `discovery.ts` (avahi-browse + dns.lookup, мерж адресов, отсев IPv6 link-local), `ssh.ts` (через `ssh`/`sshpass` + `mosquitto_*` + systemd-run), `audit.ts`. Все 35 tools работают как раньше. Smoke-test на A25NDEMJ: discover + exec + getInfo + getMetrics + mqttListTopics — все ОК.
- 2026-05-07 — bash-скилл `wb-mqtt-serial`: три критичных бага найдены через субагент при попытке включить канал `Uptime` на WB-MR6C: (1) `device/LoadConfig` НЕ возвращает channels (только fw+model+parameters); (2) `templates/GetTemplate` RPC даёт таймаут на wb-2602; (3) пример `confed/Editor/Save` с `"content":"<JSON>"` (с кавычками) кладёт опрос всей шины с `requires objectValue` — content должен быть JSON-объектом, не string. В скилле описан правильный путь: jq -nc --rawfile c ... '... content:($c|fromjson) ...'. Шаблоны теперь читаем из `/usr/share/wb-mqtt-serial/templates/config-<device.id>.json`. Те же фиксы перенесены в `wiren-board` и `wb_modbus_template`/`wb_modbus_channels` MCP-tools (template — file-based, channels — параметры fw, не каналы).
- 2026-05-07 — `wb-rules` RPC: на самом деле есть полный набор `Editor/{List, Load, Save, Remove, ChangeState, Rename}`. Я ошибочно подтвердил субагенту, что "Editor/Remove нет" — это была неверная интуиция. Проверил руками на A25NDEMJ: `Remove` работает, возвращает `result:true`. `ChangeState {path, enabled:false}` переименовывает в `<name>.js.disabled` и возвращает `result:true`. Обратный `enabled:true` через тот же путь — на этой прошивке возвращает `result:false` и не включает (надо удалять `.disabled` руками + Save). Bash-скилл и мастер обновлены полным списком методов; добавлен MCP-tool `wb_rules_disable`; `wb_rules_delete` теперь использует `Editor/Remove` напрямую (было через try-catch на ложно-несуществующий RPC).
- 2026-05-07 — `troubleshooting`: тест на A25NDEMJ нашёл реальный failed unit `fstrim.service` (status=64/USAGE — отсутствует SD-карта в `/mnt/sdcard`). В скилле было: `journalctl -p err -n 50` без `--since` (мог показать ошибки недельной давности — обещание «за час» нарушалось); не был упомянут `systemctl status <unit>` (даёт exit code и Result, ключ к диагнозу status=N/...); порог свободного места был абсолютный (100 МБ), стал процентный; добавлен паттерн fstrim/USAGE в таблицу.
- 2026-05-07 — `troubleshooting-serial`: реально-исполненная debug-сессия на A25NDEMJ выявила несколько багов в рецепте. (1) `journalctl ... -n 500 > $LOG` молча обрезает окно: при debug=true драйвер пишет ~25 строк/сек, на 120с лог должен быть ~3000 строк, а в файле всегда 500. Заменено на `journalctl --since "$START_TS" --no-pager` (без `-n`). (2) `START_TS` теперь захватывается до `sleep`, не считается через `${duration+5} seconds ago` ретроактивно. (3) Скрипт получил `trap restore_off EXIT INT TERM` — гарантированный возврат `debug:false` даже при упавшем рестарте драйвера. (4) Sed-replace с группой захвата сохраняет исходное форматирование `"debug" : false`. (5) Разделение «компактный one-liner / читаемый» убрано — оставлен только читаемый, scp+ssh, без 3-уровневых кавычек. Те же фиксы в MCP-tool `wb_serial_debug`. Дополнительно: regex гистограммы (`device modbus:\\K\\d+`) пропускает шумные шаблоны (`[mqtt] connection lost` и т.п.), теперь требует подгружать сырые последние 30 строк рядом; `ports/Load` возвращает только активные порты; `wb_modbus_scan` может молча пропускать живые WB-устройства (наблюдалось на WB-MAP6S, MQTT-каналы при этом обновляются — обязательно проверять `device/Probe`); регистры 121-122 не универсальны (только реле/диммеры/MCM); `templates/GetTemplate` заменён на чтение файла шаблона. Те же доменные фиксы — в MCP-двойнике скилла.
- 2026-05-07 — `controller-backup`: полный цикл на A2V6W7I6 (продакшн контроллер, uptime 83 дня) сошёлся, архив 12 МБ скачан. Найдено: (1) **критично** — аудит-секция `mntdata` использовала `for d in /mnt/data/*/` без `dotglob` → не видела скрытые каталоги: `.dockge` (compose stacks Dockge), `.wb-restore`, `.wb-update`. Без починки бэкап молча терял compose-проекты. Исправлено `shopt -s dotglob` + расширён список исключений. (2) Чеклист в начале фазы 1 не отражал шаг 1b (state-snapshot) — добавлен. (3) Docker-восстановление в RESTORE-таблице зашитно полагалось на `wb-docker-manager.sh`; на этом контроллере его нет (ставился прямым apt) — добавлен fallback. (4) Прояснено, что core-tar рекурсивно включает `mnt/data/etc`, поэтому `/mnt/data/etc/docker/` и симлинки конфигов туда попадают и дублировать их не нужно. Те же фиксы — в `lib/audit.ts` MCP-сервера.
- 2026-05-07 — тот же `dotglob`-баг найден в `wb-ai-helper-desktop/src/server/audit.ts:31`. По разрешению пользователя ушёл туда отдельной веткой `fix/audit-mntdata-dotglob` от `origin/main`, через PR #3 слит в main, тэг `v0.12.1`, release workflow собрал и опубликовал релиз с linux/windows/AppImage бинарниками: <https://github.com/wirenboard/wb-ai-helper-desktop/releases/tag/v0.12.1>.
- 2026-05-07 — `controller-update`: recon на обоих контроллерах. На wb7-A25NDEMJ 38 upgradable без ядра, на wb8-A2V6W7I6 95 upgradable с обновлением ядра (`linux-image-wb8 6.8.0-wb140→wb153`) и мажорным Docker stack (`docker-ce 28→29`, `containerd.io 1→2`, `compose-plugin 2→5`). Поправлено: (1) recon не делал kernel-mismatch check (мастер-скилл считает это первым шагом при проблемах после обновления — но перед обновлением проверять ещё важнее); добавлено в шаг 1. (2) Пороги свободного места `>=1ГБ/500МБ-1ГБ/<500МБ` явно прописаны (на A2V6W7I6 `/` 66% близко к границе для крупного апгрейда). (3) Противоречие в скилле: «грабли» гласили "apt update/upgrade — через systemd-run", а сам recon делал `apt-get update` напрямую через ssh. Уточнено: `apt-get update` синхронно ок (2-5 сек), `apt upgrade` — через systemd-run/`wb_ssh_exec_async`. (4) Добавлен раздел про мажорные апгрейды (Docker/containerd/u-boot/linux-image) — отдельным апгрейдом, после прочтения changelog. (5) Подсчёт upgradable дополнен `sort -u` (на arm64-контроллерах с armhf multiarch один пакет считается дважды). Те же правки — в MCP-двойнике.
- 2026-05-07 — `hardware-modules`: read-only тест на A2V6W7I6 (wb8). В скилле было 4 фактических расхождения с реальностью: (1) «mod1-4» — на wb84 реально 3 mod-слота (и `wb84-mod1` без UART). (2) Module-ID в таблице (`wbe2-i-zigbee`, `wbe2-i-can`, `wbe2-i-rs485`) **не существуют** в schema — реальные `wbe2r-r-zigbee`, `wb67-can-rs485`, `wbe2-i-rs232` (только этот совпал). (3) Слоты `w1`/`w2` (1-Wire), `wbmz5` (БРП), `wbc` (модем), `extio*` (WBIO) — не упоминались вовсе или вскользь. (4) Проверка `ls /dev/ttyMOD<N>` после установки модуля ложно-негативна для не-UART модулей (GPIO, 1-Wire, extio, WBMZ5) — добавлены конкретные альтернативы. Те же правки в MCP-двойнике.
- 2026-05-07 — `software-install`: реальная установка Node-RED на A25NDEMJ. Сначала по нативному пути (apt+npm) — прошло, но пользователь сказал, что предпочитает Docker для всего, кроме Z2M (привязка к адаптеру). Скилл переписан: новая политика «Docker по умолчанию» наверху, нативный Z2M-блок остался как исключение, нативный Node-RED уехал в раздел «fallback». Native-Node-RED удалён с A25NDEMJ, контроллер в исходное состояние. Затем агент развернул Node-RED в Docker (compose-stack `/mnt/data/nodered/`), нашёл ещё 4 фикса в скилле: (1) `wb-docker-manager.sh` НЕ ставит `docker-compose-plugin` — добавлен отдельный шаг. (2) Если первая установка прервалась, повторный запуск скрипта молча выходит (ориентируется на `command -v docker` = cli-пакет, а не на демон) — добавлен раздел про `dpkg --configure -a` + `apt install --reinstall docker-ce`. (3) Bind-mount `./data:/data` для Node-RED требует `chown 1000:1000`, иначе restart-loop с EACCES — упомянуто. (4) `host.docker.internal` под Linux Docker Engine не резолвится без `extra_hosts: [host.docker.internal:host-gateway]` — добавлено в пример compose. Те же фиксы — в MCP-двойнике. Web-UI Node-RED работает в контейнере на http://wirenboard-A25NDEMJ.local:1880/.
- 2026-05-07 — `hardware-modules`/`software-install`/`zigbee`/`history`/`bugreport`/`diagrams`/`documentation-search`: см. соответствующие строки таблицы Фазы 1 — у каждого скилла записаны конкретные находки (3-7 правок) и применённые фиксы.
- 2026-05-07 — Vega/Vega-Lite SVG-рендер вендорен в mcp-server. Добавлены deps `vega@6` + `vega-lite@6` (75 пакетов), `mcp-server/src/lib/history-chart.ts` со всеми 7 типами чартов (line/bar/area/point/histogram/heatmap/boxplot) и логикой 1/2/3+ unit-групп (одна шкала / двойная ось / нормализация). Новый MCP-tool `wb_history_chart`: один вызов ходит за данными в `db_logger/history/get_values`, строит SVG, отдаёт inline или сохраняет в файл по `outputPath` (если SVG >200 КБ). Smoke-test на A25NDEMJ live: одна серия (CPU Temp 30 точек), две серии той же единицы (CPU + Board Temp), heatmap — все три SVG валидные (13-16 КБ). Поправлены счётчики tool'ов в `mcp-server/README.md` (35→37 — добавились `wb_rules_disable` и `wb_history_chart`). Скилл `skills/mcp/history/SKILL.md` дополнен — `wb_history_chart` теперь рекомендованный путь визуализации.
- 2026-05-07 — **Фаза 2a: прогон 37 tools.** Найдено 7 багов, все исправлены. Активация фиксов требует рестарта MCP. Подробно:
  - **(1) `wb_ssh_exec_async` log redirect.** `systemd-run --collect bash -c 'CMD > LOG 2>&1'` — редирект применялся только к последней команде из `CMD`, если в `CMD` есть `;` или `&&`. Все 30 итераций цикла теряли вывод; в логе оказывалась только одна последняя строка. Симптом: `wb_job_tail` отдавал пустой `lines` для активной задачи. Фикс — обернуть `CMD` в group: `bash -c '{ CMD; } > LOG 2>&1'`. `lib/ssh.ts:145`.
  - **(2) `wb_mqtt_controls`/`mqtt_devices`/`mqtt_list` парсер.** `mosquitto_sub -v` использует пробел как разделитель `topic payload`, но имена контролов **бывают с пробелами** (`Input 0`, `Input 0 counter` у WB-MR6C, `CPU Temperature`, `Board Temperature`). Парсер резал по первому пробелу — терял суффикс имени топика, остаток уходил в payload. Фикс — `mosquitto_sub -F '%t\t%p'` + парсинг по TAB. `lib/ssh.ts` `mqttListTopics`. Также добавлен метод `mqttRead`/в `wb_mqtt_read` — там было `'${topic}'` без `shellQuote` (баг безопасности при `'` в topic, плюс пара пробелов).
  - **(3) `wb_confed_save` content как строка.** `z.unknown()` принимает что угодно. LLM-клиенты часто передают content как JSON-строку (а не объект), и confed RPC записывает её escape-нутой в файл, ломая конфиг (`wb-mqtt-knx` упал в failed после моего теста). Фикс — `typeof content === 'string'` → `JSON.parse` перед отправкой в RPC. `tools/config.ts`.
  - **(4) `wb_rules_save`/`wb_rules_load` путь.** Использовали абсолютный `/etc/wb-rules/${name}.js`; wbrules Editor RPC интерпретирует path как относительный к `/etc/wb-rules/`. В итоге Save создавал файл в `/etc/wb-rules/etc/wb-rules/<name>.js`, Load оттуда же читал и фейлился с «File not found» (existing rules.js тоже не загружался). Подтверждено на A25NDEMJ. Фикс — `path: ${name}.js`. `tools/rules.ts`.
  - **(5) `wb_audit` парсер секций.** `cat /usr/lib/wb-release` в скрипте идёт **без trailing \n**; следующий `echo "===WB-AUDIT===manual"` в pipeline `;`-цепочке слипается с последней строкой: `REPO_PREFIX====WB-AUDIT===manual\n`. Регекс `/^===WB-AUDIT===([a-z]+)$/m` не matches маркер не на начале строки — секция `manual` поглощается секцией `release`, а manual-список пакетов вылетает в пустой массив. Фикс — `printf "\n===WB-AUDIT===NAME\n"` вместо `echo` для всех маркеров (ведущий `\n` гарантирует начало строки). `lib/audit.ts:5-19`.
  - **(6) `wb_modbus_template` — поиск через скан файлов.** Был цикл по `/usr/share/wb-mqtt-serial/templates/*.json` с `jq -r '.device_type'` на каждом. На A25NDEMJ цикл падал с exit 255 (видимо, jq на каком-то файле или ssh-таймаут), tool возвращал «не найден» даже для существующего шаблона. Пользователь напомнил, что в терминологии WB список шаблонов отдаёт RPC: `wb-mqtt-serial/config/Load` → `.types[].types[]` (поля `type`, `mqtt-id`, `name`, `deprecated`). Фикс — `wb_modbus_template` теперь ходит RPC, маппит `device_type → mqtt-id`, читает `/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json`. Добавлен новый tool `wb_modbus_templates_list`, отдающий плоский список всех типов с группой. `tools/serial.ts`.
  - **(7) `wb_modbus_scan` пропущенные параметры.** RPC `wb-mqtt-serial/port/Scan` требует `data_bits`/`parity`/`stop_bits` (все три), которых tool не передавал. Также `mode: "fast"` отсутствует в enum schema (только `all` поддерживается). Фикс — добавлены defaults `data_bits=8`/`parity="N"`/`stop_bits=2`, описание про `fast` исправлено. `tools/serial.ts`.
  - Bash-скиллы тоже задеты — поправлены парсеры `mosquitto_sub -v`, не учитывающие пробелы в именах контролов: `skills/bash/history/SKILL.md` (awk -F'\\t' вместо `[/ ]`), `skills/bash/wiren-board/SKILL.md` (новый блок «Имена с пробелами», главное правило заменено на `mosquitto_sub -F '%t\\t%p'`).
  - Параллельные вызовы (`wb_probe`+`wb_metrics` × 2 контроллера одновременно) — ОК, SshPool не блокируется. Устойчивость async к разрыву ssh — повторим после рестарта MCP с фиксом log redirect.
- 2026-05-07 — Повторная проверка после рестарта MCP. Все 7 фиксов активны: async-job log redirect (5 строк цикла + final в логе), mqtt_controls корректно отдаёт `Input 0`/`Input 0 counter` отдельными topics, confed_save распарсил content-строку и записал объект (knx-конфиг и сервис в норме), rules_save кладёт в `/etc/wb-rules/<name>.js` без вложенности и rules_load читает обратно, audit `release`-секция чистая (`REPO_PREFIX=` без хвоста) и `manualPackages` заполнен (118 пакетов), modbus_template для `WB-MR6C` нашёл `mqtt-id=wb-mr6c` через RPC и отдал 107 каналов, modbus_scan без явных serial-параметров отрабатывает (используются defaults). Дополнительная находка: `wb_modbus_templates_list` отдавал жирный объект (63 КБ, 254 шаблона со всеми полями включая `hw[].signature`) — переполнял токен-лимит. Урезал до `{type, mqtt-id, name, deprecated, group}`, скрыл deprecated по умолчанию, добавил параметр `filter` для подстроки. После следующего рестарта будет компактным.
- 2026-05-07 — Live-тест factory reset на A25NDEMJ (тестовый контроллер). Запуск через `wb_ssh_exec_async '/usr/bin/wb-factoryreset --force'`, контроллер ушёл на FIT-прошивку, вернулся через ~3.5 мин. Релиз откатился wb-2602 → wb-2410 (зашитый factoryreset.fit), ядро 5.10.35-wb181 → wb172, `/mnt/data/` стёрт целиком (4% → 1%), `/etc/wb-rules/` обнулён до дефолтных. Host-keys полностью пересгенерированы (ECDSA `/MTLL...A8` → `YgQ1N...R8`, RSA `n1y3...OU` → `ydxZ...Rc`). **MCP-сервер продолжил подключаться** — фикс `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null` работает (ранее с `accept-new` упал бы с `REMOTE HOST IDENTIFICATION HAS CHANGED!`). Заодно нашли нюанс: `wb_state_save` snapshot хранится в `/mnt/data/ai/`, который факторитом стирается — `wb_state_diff` после reset невозможен; нужен локальный download snapshot перед reset. Документировано в `/controller-update` (Сценарий D, оба flavor) и в `/wiren-board` правилах безопасности (требование явного подтверждения + бэкап).
