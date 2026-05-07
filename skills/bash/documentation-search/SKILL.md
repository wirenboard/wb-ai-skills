---
name: documentation-search
description: Поиск в документации Wiren Board — вики, GitHub, веб-поиск. Порядок источников и стратегии.
allowed-tools: Bash Read WebFetch WebSearch
---

# documentation-search

Поиск в документации Wiren Board. **Сначала проверь, нет ли ответа на контроллере** (`/usr/share/wb-mqtt-serial/templates/`, `dpkg -l`, RPC `device/LoadConfig`, локальный файл) — на железе документация под установленную прошивку, в интернете может быть для другой версии.

## Порядок: внешний поисковик → конкретные URL → fallback

### 1. WebSearch с `site:` — основной путь

**Поисковик через Google/Bing работает по WB-вики лучше встроенного `Special:Search`** (тот часто не находит результаты по русским запросам). Используй с `site:`-фильтром:

```
WebSearch 'site:wiki.wirenboard.com <запрос>'
WebSearch 'site:github.com/wirenboard <запрос>'
```

Из топа результата бери URL — потом `WebFetch <URL>` читает страницу. Один `WebSearch` обычно даёт хороший заход; если не нашёл — переформулируй (синонимы, английский), но **не трать больше 2-3 вызовов** на одну тему.

Примеры:
- `WebSearch 'site:wiki.wirenboard.com WB-MR6C broadcast группа каналов'`
- `WebSearch 'site:wiki.wirenboard.com modbus relay management'`
- `WebSearch 'site:github.com/wirenboard/wb-rules defineRule cron'`

### 2. WebFetch конкретной страницы — если URL заранее известен

Прямой переход быстрее и не тратит поисковый лимит:

```
WebFetch https://wiki.wirenboard.com/wiki/<Страница>
```

**Правильный домен — `wiki.wirenboard.com`, не `wirenboard.com/wiki`.** Второй редиректит (HTTP 301) и сжигает один WebFetch впустую. Имена — `Snake_Case` / `CamelCase`, пробелы → `_`.

Типовые страницы:
- Конкретный модуль: `https://wiki.wirenboard.com/wiki/WB-MR6C` (или `WB-MR6C_v.2_Modbus_Relay_Modules`, `WB-MR6C_v.3_...`).
- Тема: `https://wiki.wirenboard.com/wiki/Wb-rules`, `https://wiki.wirenboard.com/wiki/Modbus`.
- Списки/индексы: `https://wiki.wirenboard.com/wiki/Service:RecentChanges`.
- Changelog прошивок: `https://wiki.wirenboard.com/wiki/Firmware_Changelog`.

### 3. GitHub — исходники, шаблоны, READMEs

```
WebFetch https://github.com/wirenboard/<repo>/blob/main/README.md
```

Для **сырого содержимого** (без HTML-обёртки) → `raw.githubusercontent.com`:

```
WebFetch https://raw.githubusercontent.com/wirenboard/wb-rules/master/README.md
```

Имена файлов в `templates/<repo>` непредсказуемы (часто `config-<lowercased-id>.json` с суффиксами `-v2`, `-nc` и т.п.) — **не угадывай**. Список файлов через GitHub-API:

```bash
curl -s 'https://api.github.com/repos/wirenboard/wb-mqtt-serial/contents/templates' | jq -r '.[].name' | grep -i mr6c
```

Или, если есть `gh`:

```bash
gh api repos/wirenboard/wb-mqtt-serial/contents/templates --jq '.[].name'
```

Страницы вида `https://github.com/.../tree/main/<dir>` — JS-SPA, `WebFetch` отдаёт почти пустой markdown без листинга. Не используй.

## Когда ответа нет в публичной доке

Реальный кейс на этой проверке: в публичной доке нет цельного «как сделать broadcast-команду на все WB-MR6C» — собирается из `Modbus.md` (broadcast = адрес 0) + `Relay_Module_Modbus_Management` (рег. 100-121 для on/off/toggle). Если по теме нет одной готовой страницы — собери ответ из 2-3 страниц и явно укажи в ответе пользователю, что цельной инструкции нет, ты собрал её сам.

## Грабли

- **Домен `wirenboard.com/wiki/...` 301-редиректит** на `wiki.wirenboard.com/wiki/...`. Любой `WebFetch` на старый домен — потерянный вызов. В мастер-скилле `wiren-board` тоже правильный домен.
- **`Special:Search` на вики WB слабее Google** на русских запросах. Не используй как основной поиск.
- **Страницы `github.com/.../tree/...`** — JS-SPA, не парсятся `WebFetch`. Только GitHub-API или `raw.githubusercontent.com` для отдельных файлов.
- **`raw.githubusercontent.com/<repo>/main/<path>`** — ветка может называться `master`, не `main`. Если 404 — попробуй `master`.
- **Шаблоны wb-mqtt-serial** удобнее тянуть с контроллера (`/usr/share/wb-mqtt-serial/templates/`), а не из репо — на железе версия под установленную прошивку.
- **Лимит WebSearch** — установлено эвристически 2-3 вызова на одну тему; если так и не нашёл — пользователь должен уточнить вопрос или дать прямой URL.
