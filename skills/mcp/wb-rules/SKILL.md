---
name: wb-rules
description: "Wiren Board rules engine via MCP. Scripts in /etc/wb-rules/*.js on ES5. defineRule (whenChanged, asSoonAs, when, cron), defineVirtualDevice, PersistentStorage. Authoring, editing, and debugging automation rules."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-rules (MCP)

Wiren Board rules engine. Scripts in `/etc/wb-rules/*.js`, reusable modules in `/etc/wb-rules-modules/*.js`. Language — **ES5** (no `let`/`const`/arrow functions) plus WB-specific syntactic sugar. Edit rule files via `wb_rules_*` MCP tools (JS validation + engine reload). Module files — via `wb_write_file` (no RPC for modules, the engine picks them up itself).

Load this on "make it so that...", "when X — do Y", on a timer/event/button/motion, when editing in `/etc/wb-rules/`, mention of `defineRule`, virtual devices.

The canonical documentation is the README of the repository <https://github.com/wirenboard/wb-rules>. If unsure about syntax — `WebFetch` the README, don't guess.

## Tool routing

| Intent | Tool |
|--------|------|
| List rules (including disabled) | `wb_rules_list` |
| Read a rule | `wb_rules_load` |
| Create or update a rule | `wb_rules_save` (JS validation + reload) |
| Delete a rule | `wb_rules_delete` (RPC `Editor/Remove`, only with explicit user OK) |
| Disable a rule without deleting | `wb_rules_disable` (RPC `Editor/ChangeState`, `<name>.js` → `<name>.js.disabled`) |
| Read a control's type/value/meta | `wb_mqtt_read` |
| List devices / controls | `wb_mqtt_devices`, `wb_mqtt_controls` |
| Engine logs after Save | `wb_logs` `unit=wb-rules` |
| Write a module `/etc/wb-rules-modules/*.js` | `wb_write_file` (no RPC for modules) |
| Value history for rule diagnostics | `wb_history` |

Rule names in tool params — **with the `.js` extension** and without a path prefix: `my-rule.js`, not `/etc/wb-rules/my-rule.js`.

## Workflow: writing a rule

1. **Find the channel type** before writing — `wb_mqtt_read` for `/devices/<d>/controls/<c>/meta/type`. The type determines what to write into `dev[...]` (see types table below).

2. **Check conflicts with existing rules** — mandatory step before writing code:
   - `wb_rules_list` — see if a similar rule already exists.
   - `wb_rules_load` for suspicious files.
   - **Explain to the user in words and tables** how the new rule will interact with existing ones. Engineers don't fear code — offer to show it if needed, but first a state table or diagram:

   ```
   Input A (button) | Sensor B (leak) | Expected | Actual      | Status
   -----------------+-----------------+----------+-------------+-----------
   OFF -> ON        | inactive        | relay on | relay on    | OK
   OFF -> ON        | active          | relay off| relay on    | CONFLICT
   ON -> OFF        | active          | relay off| relay off   | OK
   ```

   If no conflicts — briefly describe how the two rules work together and in which cases which one "takes priority". Get confirmation before saving if there are conflicts or non-trivial interaction.

3. **Show the new rule's logic** — before code:
   - For simple logic — an "input → output" table.
   - For branches, states, chains — a Mermaid diagram (`flowchart TD`, `stateDiagram-v2`, `sequenceDiagram`).
   - Ask "is this the desired behavior?" and wait for confirmation.

   Example:
   ````
   ```mermaid
   flowchart TD
       A[IN1 changed] --> B{Leak active?}
       B -- yes --> C[Valve closed, notify]
       B -- no --> D{Button on?}
       D -- yes --> E[Open valve]
       D -- no --> F[Close valve]
   ```
   ````

4. **Write the rule** with correct value types (see below).

5. **Save via `wb_rules_save`** with params `{path: "<name>.js", content: "<JS code>"}`. The tool itself validates syntax and reloads the engine — `systemctl restart wb-rules` is not needed. If the response has a validation error — read it, fix, re-save.

6. **Check logs right after Save** — `wb_logs` `unit=wb-rules` `since=10s`. Look for `can't convert`, `SyntaxError`, `TypeError`, `ReferenceError`. If present — fix and re-save. Don't wait for the user to complain.

### Disable a rule without deleting

Load via `wb_rules_load`, add `return; // wb-la-disabled` as the first line inside each `then: function(...) {`, save via `wb_rules_save`. Re-enable — remove that line, save.

**Before disabling a file with multiple rules — warn.** If the user asked to disable one rule but the file has several — say so explicitly and get confirmation. For example: "The file `wb-la-kran-protect.js` has two rules: `wb-la-kran-toggle` and `wb-la-kran-leak`. Disabling the entire file — both will stop working. Continue?"

**Deleting a rule (`wb_rules_delete`) — only with explicit user confirmation.**

## ES5 and constraints

- **var**, regular `function`. No `let`, `const`, arrow functions, template strings, destructuring, `class`, `async/await`.
- **In JS code only ASCII operators**: `<=`, `>=`, `!=`, `*`, `/`. Unicode characters cause SyntaxError in Duktape.
- Side effects in `when` / `asSoonAs` / `whenChanged`-function are unacceptable — the engine calls them unpredictably.
- Working way to share state between rules: `PersistentStorage({global: true})` or a module (`module.static`). Plain globals **don't cross** files.

## Control types and values

The value in `dev[...]` is coerced to a native JS type by the control's `meta/type`:

| type | JS value type |
|------|---------------|
| `switch`, `alarm` | `boolean` (`true`/`false`) |
| `value`, `range`, `temperature`, `power`, `voltage`, `current`, `pressure` | `number` |
| `text` | `string` |
| `pushbutton` | fires as event (button), value — `number` (press counter) |
| `rgb` | `string` of form `"R;G;B"` |
| unknown | `string` |

**The most common error is `switch = 1` instead of `true`:**

```js
dev["wb-mwac_25/K1"] = true;    // switch
dev["wb-mr6c_7/K1"] = false;    // switch
dev["wb-mwac_25/K1"] = 1;       // ERROR: can't convert control value '1' (type float64) to datatype '1'
```

Reading an uninitialized control — `undefined`. For meta — `null` if control/device doesn't exist:

```js
if (dev["d/c"] === undefined) return;   // control exists but no value yet
if (dev["d/c#error"] === null) ...      // control/device doesn't exist at all
```

## Accessing controls

Three equivalent forms (from the README):

```js
dev["device/control"]   // canonical, always works
dev["device"]["control"]
dev.device.control
```

The only hard rule: **names with spaces, Cyrillic, hyphens, and digits at the start — only via bracket notation**:

```js
dev["wb-msw-v4_20/Temperature"]             // ok
dev["wb-msw-v4_20"]["Temperature"]          // ok
dev.wb-msw-v4_20.Temperature                // SyntaxError (hyphen)
dev["hwmon"]["CPU Temperature"]             // ok (space)
dev.hwmon.CPU Temperature                   // SyntaxError (space)
```

`dev["d/c"]` is always the safe choice, use it by default.

### Accessing meta

After `#` — meta field:

```js
dev["wb-mr3_48/K1#error"]       // read /meta/error
dev["wb-mr3_48/K1#readonly"]
dev["virDev/cell#max"] = 255    // write max for a virtual device
```

Can also be used as a trigger — see `asSoonAs` and `whenChanged` below.

## defineRule: four trigger types

```js
defineRule(name, {
  <trigger>: ...,
  then: function (newValue, devName, cellName) { ... }
});
```

`then` always receives 3 arguments, all `undefined` if the rule wasn't fired by a control change.

### 1. `whenChanged` — on control change (recommended)

Fires when the listed controls change, or at engine startup if there's a retained value in MQTT.

```js
defineRule("light_toggle", {
  whenChanged: "wb-mcm8_16/Input 1",
  then: function (newValue, devName, cellName) {
    if (newValue) dev["wb-mr6c_7/K1"] = !dev["wb-mr6c_7/K1"];
  }
});

// Multiple channels:
defineRule("any_light", {
  whenChanged: ["wb-gpio/A1_OUT", "wb-gpio/A2_OUT"],
  then: function (newValue, devName, cellName) {
    log("{}/{} = {}", devName, cellName, newValue);
  }
});

// Computed trigger: fires when the expression's result changes
defineRule("threshold", {
  whenChanged: [
    "wb-msw-v4_20/Temperature",
    function () { return dev["wb-msw-v4_20/Temperature"] > 25; }
  ],
  then: function (newValue) { log("over 25: {}", newValue); }
});
```

Works with `pushbutton` — fires on each press.

### 2. `asSoonAs` — on condition edge (0->1)

Fires when the condition function transitions `false -> true`. Doesn't re-fire until it returns to `false` and then `true` again.

```js
defineRule("overheat_start", {
  asSoonAs: function () {
    return dev["wb-msw-v4_20/Temperature"] > 40;
  },
  then: function () { dev["wb-mr6c_7/K2"] = true; }
});
```

### 3. `when` — on condition (level-triggered)

Called every time the engine re-evaluates rules and the condition is true. Usually `asSoonAs` or `whenChanged` is what you need — `when` is rarely optimal.

```js
defineRule("while_hot", {
  when: function () { return dev["wb-msw-v4_20/Temperature"] > 40; },
  then: function () { log("still hot"); }
});
```

### 4. `when: cron(...)` — on schedule

**Cron in wb-rules is 6-field, the first field is SECONDS. This is NOT standard Linux cron (5 fields).** The most frequent error is writing `"0 * * * 5"` expecting "on Fridays"; in fact it's parsed as `sec=0 min=* hour=* dom=* mon=5` (every minute of May).

Syntax of [robfig/cron/v3](https://pkg.go.dev/github.com/robfig/cron/v3): `<sec> <min> <hour> <dom> <mon> [<dow>]` (last optional). Aliases `@hourly`, `@daily`, `@weekly`, `@monthly`, `@yearly` are supported, plus `@every <dur>` (e.g. `@every 30s`, `@every 5m`).

Comparison with system cron:

| Task | Linux cron (`/etc/cron.d`) | wb-rules `cron(...)` |
|------|----------------------------|----------------------|
| daily at 20:00 | `0 20 * * *` | `0 0 20 * * *` |
| every Friday at 08:00 | `0 8 * * 5` | `0 0 8 * * 5` |
| every 30 sec | -- | `@every 30s` |
| every minute | `* * * * *` | `0 * * * * *` |

If you see a 5-field string in code — that's **almost certainly a bug**: prepend `0 ` for seconds.

```js
defineRule("night_light_off", {
  when: cron("0 0 23 * * *"),        // every day at 23:00
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
  when: cron("0 0 8 * * 5"),         // every Friday at 08:00
  then: function () { /* ... */ }
});
```

Cron survives engine reload.

## Timers

### setTimeout / setInterval (regular JS)

```js
var id = setTimeout(function () { ... }, 2000);
clearTimeout(id);

var tickId = setInterval(function () { ... }, 500);
clearInterval(tickId);
```

**`setInterval` works as expected** (it's plain ES5). Minimum — 1 ms, but don't go below 10 ms — CPU.

Example "blink for 10 fires":

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

### startTimer / startTicker (WB-specific, integrated with rules)

Timers are named, accessed via `timers.<name>`. A timer firing is an event that can be a `when` trigger.

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

// Ticker — same, but repeating
startTicker("heartbeat", 5000);
timers.heartbeat.stop();   // stop
```

`setTimeout/setInterval` — simpler; `startTimer/startTicker` — when integration with `when: timers.X.firing` is needed.

## defineVirtualDevice

Creates MQTT topics `/devices/<id>/controls/<cell>` visible in the UI and accessible via `dev[]`.

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

**Cell properties:**

| Field | Purpose |
|-------|---------|
| `title` | string or `{en, ru}` |
| `type` | see types above |
| `value` | default on first start |
| `units` | unit of measurement, published to `/meta/units` |
| `min`, `max` | for `value`/`range` |
| `precision` | number of decimal digits |
| `readonly` | `true` — read-only; default true for most, false for `switch`/`pushbutton`/`range`/`rgb` |
| `order` | UI display order |
| `enum` | dictionary "value → {en, ru}" for text display |
| `forceDefault` | `true` — reset to `value` on every restart (default false) |
| `lazyInit` | `true` — don't publish until first write |

## Logging

```js
log(fmt, ...)          // info
log.info(fmt, ...)
log.debug(fmt, ...)    // visible only with WB_RULES_OPTIONS="-debug"
log.warning(fmt, ...)
log.error(fmt, ...)
debug(fmt, ...)        // alias for log.debug
```

Goes to syslog (read via `wb_logs` `unit=wb-rules`) and to MQTT topics `/wbrules/log/<level>` (read via `wb_mqtt_read`).

Formatting:
- `"{}"` — placeholder, `log("a={} b={}", "q", 42)` → `"a=q b=42"`
- `"{{"` — literal `{`
- `.xformat(...)` — same as format, plus `{{expr}}` for arbitrary JS expressions: `"Value: {{dev['abc/def']}}"`.

## MQTT operations

### publish — arbitrary topics

```js
publish(topic, payload)                   // QoS 0, not retained
publish(topic, payload, 2)                // QoS 2
publish(topic, payload, 2, true)          // retained
```

For device parameters use `dev[...] = ...` — it publishes with the right QoS/retained itself. `publish()` — only for topics outside the device model.

### trackMqtt — subscribe to any topic

```js
trackMqtt("/devices/wb-adc/controls/Vin", function (msg) {
  // msg = {topic: "...", value: "..."}
  log.info("{}={}", msg.topic, msg.value);
});
```

## Shell commands

```js
runShellCommand("uname -a", {
  captureOutput: true,
  captureErrorOutput: true,
  input: "stdin text",
  exitCallback: function (code, stdout, stderr) {
    if (code === 0) log("out: {}", stdout);
  }
});

// equivalent: spawn("/bin/sh", ["-c", cmd], opts)
spawn("/usr/bin/ls", ["-la", "/etc/wb-rules"], {
  captureOutput: true,
  exitCallback: function (code, out) { log(out); }
});
```

## Rule management

```js
var myRule = defineRule("name", { whenChanged: "...", then: ... });
disableRule(myRule);    // stop checking
enableRule(myRule);     // re-enable
runRule(myRule);        // forcibly run then
```

## Device/Control API

```js
getDevice("wb-mr6c_7")                         // device object
getControl("wb-mr6c_7/K1")                     // control object
isControlExists("wb-mr6c_7/K1")                // bool

// Device methods:
getDevice(d).getId()
getDevice(d).controlsList()                    // array of all controls
getDevice(d).addControl(id, spec)              // virtual only
getDevice(d).removeControl(id)
getDevice(d).isVirtual()
getDevice(d).setError(str) / .getError()

// Control methods:
getControl(dc).getValue() / .setValue(v)
getControl(dc).setTitle(str) / .setDescription(str)
getControl(dc).setType(str)
getControl(dc).setUnits(str)
getControl(dc).setMin(n) / .setMax(n) / .setPrecision(n)
getControl(dc).setReadonly(b)
getControl(dc).setError(str) / .getError()
getControl(dc).setValue({value: v, notify: false})  // write without publishing
```

## Configs and aliases

```js
var cfg = readConfig("/etc/myscript.conf");   // JSON with comments //, /* */
// Wrap arrays: readConfig("x.conf").config

defineAlias("heater", "Relays/Relay 1");
heater = true;    // == dev["Relays/Relay 1"] = true
```

## PersistentStorage

Survives engine and controller restart. `{global: true}` — mandatory.

```js
var ps = new PersistentStorage("my_state", {global: true});
ps["count"] = (ps["count"] || 0) + 1;
ps["last_ts"] = Date.now();

// Objects — only via StorableObject:
ps["cfg"] = new StorableObject({temperature: 21, enabled: true});
ps["cfg"].temperature = 23;   // saved

// Removal:
ps["count"] = null;
```

## Modules

Module files live in `/etc/wb-rules-modules/*.js`. There's **no** RPC for them — write directly via `wb_write_file`. The engine picks them up itself.

```js
// /etc/wb-rules-modules/utils.js
exports.celsiusToF = function (c) { return c * 9 / 5 + 32; };
exports.const_pi = 3.14159;
// module.static — shared storage between all rules that require the module

// In a rule:
var utils = require("utils");
log("{}", utils.celsiusToF(25));
```

Don't reassign `exports`, only add properties.

## Alarms and notifications

```js
Notify.sendEmail("x@y.ru", "subj", "body");
Notify.sendSMS("+7...", "body");
Notify.sendTelegramMessage(token, chatId, "body");

Alarms.load("/etc/wb-rules/alarms.conf");   // or an object with the spec
```

The full `alarms.conf` specification is in the README.

## Full example

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

## Conventions

- File: `wb-la-<slug>.js` (hyphens, Latin), header `// wb-la: short description (Russian text is fine — controllers ship to Russian-speaking integrators)`.
- Rule name in `defineRule`: `wb-la-<slug>` (matches the file name without `.js`).
- **In responses to the user:** the script file and the rules inside it are different entities, always distinguish visually:
  - File: always with `.js` (e.g. `wb-la-kran-protect.js`)
  - Rule from `defineRule`: without `.js` (e.g. `wb-la-kran-toggle`)
  - When listing — nested structure: file on top, rules indented inside.

## Gotchas

- **switch = true/false, NOT 0/1.** wb-rules returns native boolean — `newValue` is already `true`/`false`, don't write `=== 1 || === "1" || === true` etc., that's junk.
- **Didn't check logs after Save** — `wb_logs` `unit=wb-rules` `since=10s`. Without this, errors are silently ignored.
- **`whenChanged` on your own output** — infinite loop. Set a flag or separate in/out.
- **Side effects in `when`/`asSoonAs`/whenChanged-function** — engine calls them unpredictably. Pure logic only.
- **`let`/`const`/arrow** — SyntaxError, ES5 only.
- **Names with spaces via dot** — SyntaxError, only `dev["d/c"]` or `dev["d"]["c"]`.
- **`dev` outside a rule / outside `then` / `setTimeout` callback** — assignment ALWAYS publishes MQTT, even if the value didn't change. At the script top-level it breaks logic.
- **Publishing > 100 topics/sec** — high CPU, degradation. Optimize frequency.
- **Global variables across files** don't intersect. Use modules or `PersistentStorage({global: true})`.
- **`ps["obj"].foo = 5`** without `StorableObject` — won't save. Wrap objects in `new StorableObject({...})`.
- **`whenChanged` control overrides `asSoonAs` protection** — if the protection rule (`asSoonAs`) closes a valve/relay on alarm, while the control rule (`whenChanged` button) opens it back — it will fire even when the alarm sensor is still active: `asSoonAs` doesn't repeat until the condition resets. In the `then` of the control rule always check the blocking sensor: `if (dev["sensor/alarm"]) return;`
- **String concatenation without space** — `"journalctl -u" + unit` gives `"journalctl -uwb-rules"`. Put the space inside the string: `"journalctl -u " + unit`.

## Documentation

- README (canonical reference): <https://github.com/wirenboard/wb-rules>
- Examples: <https://github.com/wirenboard/wb-rules/tree/master/examples>
- Wiki navigation: <https://wirenboard.com/wiki/Wb-rules>
- Cron syntax (`robfig/cron/v3`): <https://pkg.go.dev/github.com/robfig/cron/v3>
