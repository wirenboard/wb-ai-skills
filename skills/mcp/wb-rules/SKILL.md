---
name: wb-rules
description: "Движок правил Wiren Board через MCP. Скрипты в /etc/wb-rules/*.js на ES5. defineRule (whenChanged, asSoonAs, when, cron), defineVirtualDevice, PersistentStorage. Создание, редактирование и отладка правил автоматизации."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-rules (MCP)

Движок правил Wiren Board. Скрипты в `/etc/wb-rules/*.js`, переиспользуемые модули в `/etc/wb-rules-modules/*.js`. Язык — **ES5** (без `let`/`const`/arrow-функций) плюс WB-специфичный синтаксический сахар. Файлы правил редактируй через MCP-tools `wb_rules_*` (валидация JS + reload движка). Файлы модулей — через `wb_write_file` (RPC для модулей нет, движок подхватит сам).

Подгружай на «сделай чтобы...», «когда X — делай Y», по таймеру/событию/кнопке/движению, при правках в `/etc/wb-rules/`, упоминании `defineRule`, виртуальных устройств.

Каноничная документация — README репозитория <https://github.com/wirenboard/wb-rules>. Если есть сомнения в синтаксисе — `WebFetch` на README, не угадывай.

## Маршрутизация tools

| Намерение | Tool |
|-----------|------|
| Список правил (включая выключенные) | `wb_rules_list` |
| Прочитать правило | `wb_rules_load` |
| Создать или обновить правило | `wb_rules_save` (валидация JS + reload) |
| Удалить правило | `wb_rules_delete` (RPC `Editor/Remove`, только с явным OK пользователя) |
| Выключить правило, не удаляя | `wb_rules_disable` (RPC `Editor/ChangeState`, `<name>.js` → `<name>.js.disabled`) |
| Прочитать тип/значение/meta контрола | `wb_mqtt_read` |
| Список устройств / контролов | `wb_mqtt_devices`, `wb_mqtt_controls` |
| Логи движка после Save | `wb_logs` `unit=wb-rules` |
| Записать модуль `/etc/wb-rules-modules/*.js` | `wb_write_file` (RPC для модулей нет) |
| История значения для диагностики правила | `wb_history` |

Имена правил в params tools — **с расширением `.js`** и без префикса пути: `my-rule.js`, не `/etc/wb-rules/my-rule.js`.

## Workflow: написать правило

1. **Узнай тип канала** перед записью — `wb_mqtt_read` для `/devices/<d>/controls/<c>/meta/type`. От типа зависит, что записывать в `dev[...]` (см. таблицу типов ниже).

2. **Проверь конфликты с существующими правилами** — обязательный шаг перед написанием кода:
   - `wb_rules_list` — посмотри, нет ли уже похожего правила.
   - `wb_rules_load` для подозрительных файлов.
   - **Объясни пользователю словами и таблицами**, как новое правило будет взаимодействовать с существующими. Инженеры не боятся кода — предложи показать если нужно, но сначала таблица состояний или диаграмма:

   ```
   Вход A (кнопка) | Датчик B (протечка) | Ожидание  | Факт        | Статус
   ----------------+---------------------+-----------+-------------+-----------
   OFF -> ON       | inactive            | реле вкл  | реле вкл    | OK
   OFF -> ON       | active              | реле выкл | реле вкл    | КОНФЛИКТ
   ON -> OFF       | active              | реле выкл | реле выкл   | OK
   ```

   Если конфликтов нет — кратко опиши, как два правила работают вместе и в каких случаях какое из них «главнее». Получи подтверждение перед сохранением, если есть конфликты или нетривиальное взаимодействие.

3. **Покажи логику нового правила** — перед кодом:
   - Для простой логики — таблица «вход → выход».
   - Для ветвлений, состояний, цепочек — Mermaid-диаграмма (`flowchart TD`, `stateDiagram-v2`, `sequenceDiagram`).
   - Спроси «такое поведение?» и дождись подтверждения.

   Пример:
   ````
   ```mermaid
   flowchart TD
       A[IN1 изменился] --> B{Протечка active?}
       B -- да --> C[Кран закрыт, уведомление]
       B -- нет --> D{Кнопка включена?}
       D -- да --> E[Открыть кран]
       D -- нет --> F[Закрыть кран]
   ```
   ````

4. **Напиши правило** с правильными типами значений (см. ниже).

5. **Сохрани через `wb_rules_save`** с params `{path: "<имя>.js", content: "<JS-код>"}`. Tool сам валидирует синтаксис и делает reload движка — `systemctl restart wb-rules` не нужен. Если в ответе ошибка валидации — читай её, правь, пересохраняй.

6. **Проверь логи сразу после Save** — `wb_logs` `unit=wb-rules` `since=10s`. Ищи `can't convert`, `SyntaxError`, `TypeError`, `ReferenceError`. Если есть — исправь и пересохрани. Не жди жалобы пользователя.

### Отключить правило без удаления

Загрузи через `wb_rules_load`, добавь `return; // wb-la-disabled` первой строкой внутри каждого `then: function(...) {`, сохрани через `wb_rules_save`. Включить обратно — убрать эту строку, сохранить.

**Перед отключением файла с несколькими правилами — предупреди.** Если пользователь попросил отключить одно правило, а в файле их несколько — скажи об этом явно и получи подтверждение. Например: «В файле `wb-la-kran-protect.js` два правила: `wb-la-kran-toggle` и `wb-la-kran-leak`. Отключу весь файл — оба перестанут работать. Продолжать?»

**Удалять правило (`wb_rules_delete`) — только с явным подтверждением пользователя.**

## ES5 и ограничения

- **var**, обычные `function`. Никаких `let`, `const`, стрелочных функций, шаблонных строк, деструктуризации, `class`, `async/await`.
- **В JS-коде только ASCII-операторы**: `<=`, `>=`, `!=`, `*`, `/`. Unicode-символы вызовут SyntaxError в Duktape.
- Side effects в `when` / `asSoonAs` / `whenChanged`-function недопустимы — движок вызывает их непредсказуемо.
- Рабочий способ шарить состояние между правилами: `PersistentStorage({global: true})` или модуль (`module.static`). Обычные глобалы **не пересекают** файлы.

## Типы контролов и значения

Значение в `dev[...]` приводится к нативному JS-типу по `meta/type` контрола:

| type | JS-тип значения |
|---|---|
| `switch`, `alarm` | `boolean` (`true`/`false`) |
| `value`, `range`, `temperature`, `power`, `voltage`, `current`, `pressure` | `number` |
| `text` | `string` |
| `pushbutton` | срабатывает как событие (кнопка), значение — `number` (счётчик нажатий) |
| `rgb` | `string` вида `"R;G;B"` |
| неизвестный | `string` |

**Самая частая ошибка — `switch = 1` вместо `true`:**

```js
dev["wb-mwac_25/K1"] = true;    // switch
dev["wb-mr6c_7/K1"] = false;    // switch
dev["wb-mwac_25/K1"] = 1;       // ОШИБКА: can't convert control value '1' (type float64) to datatype '1'
```

Чтение неинициализированного контрола — `undefined`. Для meta — `null` если контрол/устройство не существует:

```js
if (dev["d/c"] === undefined) return;   // контрол есть, но значение ещё не пришло
if (dev["d/c#error"] === null) ...      // контрола/устройства нет вообще
```

## Доступ к контролам

Три равноценные формы (из README):

```js
dev["device/control"]   // каноничная, работает всегда
dev["device"]["control"]
dev.device.control
```

Единственное жёсткое правило: **имена с пробелами, кириллицей, дефисами и цифрами в начале — только через bracket-notation**:

```js
dev["wb-msw-v4_20/Temperature"]             // ok
dev["wb-msw-v4_20"]["Temperature"]          // ok
dev.wb-msw-v4_20.Temperature                // SyntaxError (минус)
dev["hwmon"]["CPU Temperature"]             // ok (пробел)
dev.hwmon.CPU Temperature                   // SyntaxError (пробел)
```

`dev["d/c"]` — всегда безопасный выбор, используй его по умолчанию.

### Доступ к meta

После `#` — meta-поле:

```js
dev["wb-mr3_48/K1#error"]       // чтение /meta/error
dev["wb-mr3_48/K1#readonly"]
dev["virDev/cell#max"] = 255    // запись max для virtual device
```

Можно использовать и как триггер — см. ниже `asSoonAs` и `whenChanged`.

## defineRule: четыре типа триггеров

```js
defineRule(name, {
  <trigger>: ...,
  then: function (newValue, devName, cellName) { ... }
});
```

`then` всегда получает 3 аргумента, все `undefined` если правило запущено не по изменению контрола.

### 1. `whenChanged` — по изменению контрола (рекомендованный)

Срабатывает когда перечисленные контролы меняются или при старте движка, если есть retained-значение в MQTT.

```js
defineRule("light_toggle", {
  whenChanged: "wb-mcm8_16/Input 1",
  then: function (newValue, devName, cellName) {
    if (newValue) dev["wb-mr6c_7/K1"] = !dev["wb-mr6c_7/K1"];
  }
});

// Несколько каналов:
defineRule("any_light", {
  whenChanged: ["wb-gpio/A1_OUT", "wb-gpio/A2_OUT"],
  then: function (newValue, devName, cellName) {
    log("{}/{} = {}", devName, cellName, newValue);
  }
});

// Вычисляемый триггер: сработает когда выражение изменит результат
defineRule("threshold", {
  whenChanged: [
    "wb-msw-v4_20/Temperature",
    function () { return dev["wb-msw-v4_20/Temperature"] > 25; }
  ],
  then: function (newValue) { log("over 25: {}", newValue); }
});
```

Работает с `pushbutton` — срабатывает по каждому нажатию.

### 2. `asSoonAs` — по фронту условия (0->1)

Срабатывает когда функция-условие переходит `false -> true`. Не запускается повторно, пока не вернётся в `false` и снова в `true`.

```js
defineRule("overheat_start", {
  asSoonAs: function () {
    return dev["wb-msw-v4_20/Temperature"] > 40;
  },
  then: function () { dev["wb-mr6c_7/K2"] = true; }
});
```

### 3. `when` — по условию (level-triggered)

Вызывается каждый раз, когда движок пересматривает правила и условие истинно. Обычно нужен `asSoonAs` или `whenChanged` — `when` редко оптимален.

```js
defineRule("while_hot", {
  when: function () { return dev["wb-msw-v4_20/Temperature"] > 40; },
  then: function () { log("still hot"); }
});
```

### 4. `when: cron(...)` — по расписанию

**Cron в wb-rules — 6-польный, первое поле — СЕКУНДЫ. Это НЕ стандартный Linux-cron (5 полей).** Самая частая ошибка — написать `"0 * * * 5"` ожидая «по пятницам»; на самом деле это распарсится как `sec=0 min=* hour=* dom=* mon=5` (каждую минуту мая).

Синтаксис [robfig/cron/v3](https://pkg.go.dev/github.com/robfig/cron/v3): `<sec> <min> <hour> <dom> <mon> [<dow>]` (последнее опционально). Поддерживаются алиасы `@hourly`, `@daily`, `@weekly`, `@monthly`, `@yearly`, а также `@every <dur>` (напр. `@every 30s`, `@every 5m`).

Сравнение с системным cron:

| Задача | Linux cron (`/etc/cron.d`) | wb-rules `cron(...)` |
|---|---|---|
| ежедневно в 20:00 | `0 20 * * *` | `0 0 20 * * *` |
| каждую пятницу в 08:00 | `0 8 * * 5` | `0 0 8 * * 5` |
| каждые 30 сек | -- | `@every 30s` |
| каждую минуту | `* * * * *` | `0 * * * * *` |

Если видишь в коде 5-польную строку — это **почти наверняка баг**: допиши ведущий `0 ` для секунд.

```js
defineRule("night_light_off", {
  when: cron("0 0 23 * * *"),        // каждый день в 23:00
  then: function () { dev["wb-mr6c_7/K1"] = false; }
});

defineRule("check_temp", {
  when: cron("@every 30s"),
  then: function () { /* ... */ }
});

defineRule("heartbeat", {
  when: cron("@hourly"),
  then: function () { log("heartbeat"); }
});

defineRule("friday_report", {
  when: cron("0 0 8 * * 5"),         // каждую пятницу в 08:00
  then: function () { /* ... */ }
});
```

Cron переживает перезагрузку движка.

## Таймеры

### setTimeout / setInterval (обычные JS)

```js
var id = setTimeout(function () { ... }, 2000);
clearTimeout(id);

var tickId = setInterval(function () { ... }, 500);
clearInterval(tickId);
```

**`setInterval` штатно работает** (это обычный ES5). Минимум — 1 мс, но меньше 10 мс не ставь — CPU.

Пример «мигалка на 10 срабатываний»:

```js
var test_interval;
defineRule("blink", {
  whenChanged: "test/enabled",
  then: function (newValue) {
    if (!newValue) return;
    var n = 0;
    test_interval = setInterval(function () {
      dev["buzzer/enabled"] = !dev["buzzer/enabled"];
      if (++n >= 10) clearInterval(test_interval);
    }, 500);
  }
});
```

### startTimer / startTicker (WB-специфичные, интегрированы с правилами)

Таймеры именованные, доступ через `timers.<name>`. Срабатывание таймера — событие, которое может быть триггером `when`.

```js
defineRule("pulse_start", {
  asSoonAs: function () { return dev["test/enabled"]; },
  then: function () { startTimer("pulse", 1000); }  // single-shot
});

defineRule("pulse_fire", {
  when: function () { return timers.pulse.firing; },
  then: function () {
    dev["buzzer/enabled"] = false;
  }
});

// Ticker — то же, но повторяется
startTicker("heartbeat", 5000);
timers.heartbeat.stop();   // остановить
```

`setTimeout/setInterval` — проще; `startTimer/startTicker` — когда нужна интеграция с `when: timers.X.firing`.

## defineVirtualDevice

Создаёт MQTT-топики `/devices/<id>/controls/<cell>`, видимые в UI и доступные через `dev[]`.

```js
defineVirtualDevice("my_vd", {
  title: {en: "My VD", ru: "Мое устройство"},
  cells: {
    power: {
      type: "switch",
      value: false
    },
    setpoint: {
      type: "range",
      value: 22,
      min: 10,
      max: 30,
      units: "deg C",
      order: 2
    },
    mode: {
      title: {en: "Mode", ru: "Режим"},
      type: "value",
      value: 1,
      enum: {
        1: {en: "Auto", ru: "Авто"},
        2: {en: "Manual", ru: "Ручной"}
      }
    },
    last_update: {
      type: "text",
      value: "",
      readonly: true
    }
  }
});
```

**Свойства cell:**

| Поле | Назначение |
|---|---|
| `title` | строка или `{en, ru}` |
| `type` | см. типы выше |
| `value` | дефолт при первом старте |
| `units` | единицы измерения, публикуются в `/meta/units` |
| `min`, `max` | для `value`/`range` |
| `precision` | количество знаков после запятой |
| `readonly` | `true` — только для чтения; по умолчанию true для большинства, false для `switch`/`pushbutton`/`range`/`rgb` |
| `order` | порядок отображения в UI |
| `enum` | словарь «значение → {en, ru}» для текстового отображения |
| `forceDefault` | `true` — сбрасывать в `value` при каждом рестарте (по умолчанию false) |
| `lazyInit` | `true` — не публиковать до первой записи |

## Логирование

```js
log(fmt, ...)          // info
log.info(fmt, ...)
log.debug(fmt, ...)    // виден только при WB_RULES_OPTIONS="-debug"
log.warning(fmt, ...)
log.error(fmt, ...)
debug(fmt, ...)        // алиас к log.debug
```

Пишется в syslog (читай через `wb_logs` `unit=wb-rules`) и в MQTT-топики `/wbrules/log/<level>` (читай через `wb_mqtt_read`).

Форматирование:
- `"{}"` — плейсхолдер, `log("a={} b={}", "q", 42)` → `"a=q b=42"`
- `"{{"` — литеральная `{`
- `.xformat(...)` — как format, плюс `{{expr}}` для произвольных JS-выражений: `"Value: {{dev['abc/def']}}"`.

## MQTT-операции

### publish — произвольные топики

```js
publish(topic, payload)                   // QoS 0, не retained
publish(topic, payload, 2)                // QoS 2
publish(topic, payload, 2, true)          // retained
```

Для параметров устройств используй `dev[...] = ...` — он сам публикует с правильным QoS/retained. `publish()` — только для топиков вне device-модели.

### trackMqtt — подписка на любой топик

```js
trackMqtt("/devices/wb-adc/controls/Vin", function (msg) {
  // msg = {topic: "...", value: "..."}
  log.info("{}={}", msg.topic, msg.value);
});
```

## Shell-команды

```js
runShellCommand("uname -a", {
  captureOutput: true,
  captureErrorOutput: true,
  input: "stdin text",
  exitCallback: function (code, stdout, stderr) {
    if (code === 0) log("out: {}", stdout);
  }
});

// эквивалент: spawn("/bin/sh", ["-c", cmd], opts)
spawn("/usr/bin/ls", ["-la", "/etc/wb-rules"], {
  captureOutput: true,
  exitCallback: function (code, out) { log(out); }
});
```

## Управление правилами

```js
var myRule = defineRule("name", { whenChanged: "...", then: ... });
disableRule(myRule);    // перестать проверять
enableRule(myRule);     // снова включить
runRule(myRule);        // форсированно выполнить then
```

## Device/Control API

```js
getDevice("wb-mr6c_7")                         // объект устройства
getControl("wb-mr6c_7/K1")                     // объект контрола
isControlExists("wb-mr6c_7/K1")                // bool

// Методы device:
getDevice(d).getId()
getDevice(d).controlsList()                    // массив всех контролов
getDevice(d).addControl(id, spec)              // только для virtual
getDevice(d).removeControl(id)
getDevice(d).isVirtual()
getDevice(d).setError(str) / .getError()

// Методы control:
getControl(dc).getValue() / .setValue(v)
getControl(dc).setTitle(str) / .setDescription(str)
getControl(dc).setType(str)
getControl(dc).setUnits(str)
getControl(dc).setMin(n) / .setMax(n) / .setPrecision(n)
getControl(dc).setReadonly(b)
getControl(dc).setError(str) / .getError()
getControl(dc).setValue({value: v, notify: false})  // запись без публикации
```

## Конфиги и алиасы

```js
var cfg = readConfig("/etc/myscript.conf");   // JSON c комментариями //, /* */
// Массивы оборачивай: readConfig("x.conf").config

defineAlias("heater", "Relays/Relay 1");
heater = true;    // == dev["Relays/Relay 1"] = true
```

## PersistentStorage

Переживает рестарт движка и контроллера. `{global: true}` — обязательно.

```js
var ps = new PersistentStorage("my_state", {global: true});
ps["count"] = (ps["count"] || 0) + 1;
ps["last_ts"] = Date.now();

// Объекты — только через StorableObject:
ps["cfg"] = new StorableObject({temperature: 21, enabled: true});
ps["cfg"].temperature = 23;   // сохранится

// Удаление:
ps["count"] = null;
```

## Модули

Файлы модулей живут в `/etc/wb-rules-modules/*.js`. RPC для них **нет** — пиши напрямую через `wb_write_file`. Движок подхватит сам.

```js
// /etc/wb-rules-modules/utils.js
exports.celsiusToF = function (c) { return c * 9 / 5 + 32; };
exports.const_pi = 3.14159;
// module.static — shared storage между всеми правилами, которые require'ят модуль

// В правиле:
var utils = require("utils");
log("{}", utils.celsiusToF(25));
```

Не переопределяй `exports`, только добавляй свойства.

## Alarms и уведомления

```js
Notify.sendEmail("x@y.ru", "subj", "body");
Notify.sendSMS("+7...", "body");
Notify.sendTelegramMessage(token, chatId, "body");

Alarms.load("/etc/wb-rules/alarms.conf");   // или объект со spec'ом
```

Полная спецификация `alarms.conf` — в README.

## Полный пример

```js
defineVirtualDevice("climate", {
  title: {en: "Climate", ru: "Климат"},
  cells: {
    enabled: { type: "switch", value: false },
    setpoint: { type: "range", value: 22, min: 15, max: 30, units: "deg C" },
    current:  { type: "temperature", value: 0, readonly: true }
  }
});

defineRule("climate_sync", {
  whenChanged: "wb-msw-v4_20/Temperature",
  then: function (newValue) {
    dev["climate/current"] = newValue;
  }
});

defineRule("climate_control", {
  whenChanged: ["climate/enabled", "climate/current", "climate/setpoint"],
  then: function () {
    if (!dev["climate/enabled"]) {
      dev["wb-mr6c_7/K1"] = false;
      return;
    }
    var hyst = 0.5;
    var cur = dev["climate/current"];
    var sp  = dev["climate/setpoint"];
    if (cur < sp - hyst) dev["wb-mr6c_7/K1"] = true;
    else if (cur > sp + hyst) dev["wb-mr6c_7/K1"] = false;
  }
});

defineRule("climate_morning", {
  when: cron("0 0 7 * * *"),
  then: function () { dev["climate/enabled"] = true; }
});
```

## Соглашения

- Файл: `wb-la-<slug>.js` (дефисы, латиница), шапка `// wb-la: описание по-русски`.
- Имя правила в `defineRule`: `wb-la-<slug>` (совпадает с именем файла без `.js`).
- **В ответах пользователю:** файл скрипта и правила внутри — разные сущности, всегда различай визуально:
  - Файл: всегда с `.js` (например `wb-la-kran-protect.js`)
  - Правило из `defineRule`: без `.js` (например `wb-la-kran-toggle`)
  - При перечислении — вложенная структура: файл сверху, правила внутри с отступом.

## Грабли

- **switch = true/false, НЕ 0/1.** wb-rules отдаёт нативный boolean — `newValue` уже `true`/`false`, не пиши `=== 1 || === "1" || === true` и т.п., это мусор.
- **Не проверил логи после Save** — `wb_logs` `unit=wb-rules` `since=10s`. Без этого ошибки молча игнорируются.
- **`whenChanged` на свой же output** — бесконечный цикл. Ставь флаг или разделяй in/out.
- **Side effects в `when`/`asSoonAs`/whenChanged-function** — движок вызывает непредсказуемо. Только чистая логика.
- **`let`/`const`/arrow** — SyntaxError, только ES5.
- **Имена с пробелами через точку** — SyntaxError, только `dev["d/c"]` или `dev["d"]["c"]`.
- **`dev` вне правила / вне `then` / `setTimeout`-callback** — присваивание ВСЕГДА публикует MQTT, даже если значение не изменилось. На top-level скрипта это ломает логику.
- **Публикация > 100 топиков/сек** — высокий CPU, деградация. Оптимизируй частоту.
- **Глобальные переменные между файлами** не пересекаются. Используй модули или `PersistentStorage({global: true})`.
- **`ps["obj"].foo = 5`** без `StorableObject` — не сохранится. Оборачивай объекты в `new StorableObject({...})`.
- **`whenChanged`-управление отменяет `asSoonAs`-защиту** — если правило защиты (`asSoonAs`) закрывает клапан/реле при аварии, а правило управления (`whenChanged` кнопка) открывает его обратно — оно сработает даже когда аварийный датчик ещё активен: `asSoonAs` не повторяется, пока условие не сбросится. В `then` правила управления всегда проверяй датчик-блокировку: `if (dev["sensor/alarm"]) return;`
- **Конкатенация строк без пробела** — `"journalctl -u" + unit` даёт `"journalctl -uwb-rules"`. Пробел ставь внутри строки: `"journalctl -u " + unit`.

## Документация

- README (каноничный справочник): <https://github.com/wirenboard/wb-rules>
- Примеры: <https://github.com/wirenboard/wb-rules/tree/master/examples>
- Навигация на вики: <https://wirenboard.com/wiki/Wb-rules>
- Синтаксис cron (`robfig/cron/v3`): <https://pkg.go.dev/github.com/robfig/cron/v3>
