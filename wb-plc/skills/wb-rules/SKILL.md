---
name: wb-rules
description: "Wiren Board rules engine for automation — ES5 JavaScript in /etc/wb-rules/*.js. defineRule, defineVirtualDevice, PersistentStorage, timers, cron, MQTT bindings, virtual controls. Use when user wants to write an automation rule, schedule something, react to a sensor, create a virtual device, or debug a wb-rules script. NOT for custom daemons (wb-dev)."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-rules

## CRITICAL RULES

> **NEVER call `wb-cli` without `--json` from an agent.**
> Human-mode output is unparseable; always use:
> `wb-cli --json <command>`
> This applies to every call including help: `wb-cli --json <group> --help`.

**`<HOST>` variable:** in all examples below `<HOST>` means `wirenboard-<SN>.local`, where `<SN>` is the serial number (e.g. `wirenboard-AABBCCDD.local`). Substitute the real address.

Automation engine on the controller. Scripts in `/etc/wb-rules/*.js`, modules in `/etc/wb-rules-modules/*.js`. Language — **ES5** (no let/const/arrow). Manage rules via `wb-cli rules` on the controller.

Canonical docs: <https://github.com/wirenboard/wb-rules>. When in doubt — `WebFetch` the README.

## Rule operations via wb-cli

```bash
ssh root@<HOST> wb-cli --json rules list
ssh root@<HOST> wb-cli --json rules load myrule
ssh root@<HOST> 'wb-cli --json rules save myrule "$(cat /tmp/rule.js)"'
ssh root@<HOST> wb-cli --json rules disable myrule
ssh root@<HOST> wb-cli --json rules delete myrule
```

Rule names — without `.js`. After save, check logs:
```bash
ssh root@<HOST> journalctl -u wb-rules --since '10s ago' --no-pager
```

## Workflow

1. Check channel type: `ssh root@<HOST> wb-cli --json dev <device>`
2. List existing rules: `ssh root@<HOST> wb-cli --json rules list`
3. Check for conflicts with existing rules — show interaction table
4. Show logic (table or Mermaid diagram), get confirmation
5. Write rule, save via `wb-cli rules save`, check logs

## ES5 only

`var`, regular `function`. No `let`, `const`, arrow functions, template strings, destructuring, `class`, `async/await`. Unicode operators cause SyntaxError in Duktape.

## Control types and values

| type | JS value |
|---|---|
| `switch`, `alarm` | `boolean` (`true`/`false`) |
| `value`, `range`, `temperature`, `voltage`, ... | `number` |
| `text` | `string` |
| `pushbutton` | event, value is press counter |

**Most common error: `switch = 1` instead of `true`.**

```js
dev["wb-mr6c_7/K1"] = true;   // correct
dev["wb-mr6c_7/K1"] = 1;      // ERROR
```

## Accessing controls

```js
dev["device/control"]          // canonical, always works
dev["device"]["control"]       // also works
dev["d/c#error"]               // meta field
```

Names with spaces/hyphens — only bracket notation.

## defineRule: trigger types

### whenChanged — on value change (recommended)

```js
defineRule("light", {
  whenChanged: "wb-mcm8_16/Input 1",
  then: function(newValue, devName, cellName) {
    if (newValue) dev["wb-mr6c_7/K1"] = !dev["wb-mr6c_7/K1"];
  }
});

// Multiple channels:
defineRule("multi", {
  whenChanged: ["wb-gpio/A1_OUT", "wb-gpio/A2_OUT"],
  then: function(newValue, devName, cellName) { log("{}/{}", devName, cellName); }
});
```

### asSoonAs — rising edge (false->true)

```js
defineRule("overheat", {
  asSoonAs: function() { return dev["sensor/Temperature"] > 40; },
  then: function() { dev["wb-mr6c_7/K2"] = true; }
});
```

### cron — schedule (6-field, first is SECONDS)

**Not standard Linux cron.** `<sec> <min> <hour> <dom> <mon> [<dow>]`.

```js
defineRule("night_off", {
  when: cron("0 0 23 * * *"),       // daily 23:00
  then: function() { dev["wb-mr6c_7/K1"] = false; }
});

defineRule("check", {
  when: cron("@every 30s"),
  then: function() { /* ... */ }
});
```

| Task | Linux cron | wb-rules cron |
|---|---|---|
| daily 20:00 | `0 20 * * *` | `0 0 20 * * *` |
| every Friday 08:00 | `0 8 * * 5` | `0 0 8 * * 5` |

## defineVirtualDevice

```js
defineVirtualDevice("climate", {
  title: {en: "Climate", ru: "Климат"},
  cells: {
    enabled: { type: "switch", value: false },
    setpoint: { type: "range", value: 22, min: 15, max: 30, units: "deg C" },
    current: { type: "temperature", value: 0, readonly: true }
  }
});
```

## Timers

```js
setTimeout(function() { /* ... */ }, 2000);
setInterval(function() { /* ... */ }, 500);

// WB-specific named timers:
startTimer("pulse", 1000);
// then: when: function() { return timers.pulse.firing; }
```

## PersistentStorage

```js
var ps = new PersistentStorage("state", {global: true});
ps["count"] = (ps["count"] || 0) + 1;
// Objects — wrap in StorableObject:
ps["cfg"] = new StorableObject({temp: 21});
```

## Modules

```js
// /etc/wb-rules-modules/utils.js
exports.helper = function(x) { return x * 2; };

// In a rule:
var utils = require("utils");
```

Write modules via SSH (no RPC): `echo '...' | ssh root@<HOST> 'cat > /etc/wb-rules-modules/name.js'`

## Logging

```js
log("a={} b={}", val1, val2);   // info, {} placeholders
log.warning("...");
log.error("...");
```

## MQTT and shell

```js
publish(topic, payload, qos, retained);
trackMqtt("/some/topic", function(msg) { log(msg.value); });
runShellCommand("cmd", { captureOutput: true, exitCallback: function(code, out) {} });
```

## Notifications

```js
Notify.sendEmail("x@y.ru", "subj", "body");
Notify.sendSMS("+7...", "body");
Notify.sendTelegramMessage(token, chatId, "body");
```

## System cron jobs (/etc/cron.d)

For tasks outside wb-rules (shell scripts on schedule), use `/etc/cron.d/`:
```bash
ssh root@<HOST> 'cat > /etc/cron.d/my-task << EOF
*/5 * * * * root /usr/local/bin/my-script.sh >> /var/log/my-task.log 2>&1
EOF'
```
Syntax: standard cron (5 time fields + username + command). The file must not have `.` in the name.

For in-rules scheduling, use `defineRule` with a `cron` trigger — see examples above.

## Pitfalls

- **switch = true/false, NOT 0/1**
- **Check logs after every save** — errors are silent otherwise
- **whenChanged on own output** — infinite loop
- **Side effects in when/asSoonAs condition** — forbidden
- **Globals don't cross files** — use modules or PersistentStorage
- **cron 5 fields = almost certainly a bug** — prepend `0` for seconds
- **`ps["obj"].foo = 5` without StorableObject** — won't persist
- **Names with hyphens via dot notation** — SyntaxError

## What the agent does NOT do

- **Use ES6+ syntax** (`let`, `const`, arrow functions, template strings, destructuring). The wb-rules engine is **ES5 only**; ES6+ silently fails or breaks at parse time.
- **Save a rule without checking logs.** Syntax errors in wb-rules are not surfaced to the caller — only `journalctl -u wb-rules` knows. After every save, tail the journal.
- **Write `whenChanged` against the same control the rule writes to** — infinite loop, fills the journal.
- **Run side effects** (`runShellCommand`, `mqtt.publish`, control writes) **inside `when` / `asSoonAs` condition functions** — they're called on every change.
- **Delete or disable an existing rule** without first checking what it does and whether it's in production (the user may have written it months ago and forgotten).
- **Use globals as cross-file state.** Each `*.js` file in `/etc/wb-rules/` runs in its own scope; share via modules under `/etc/wb-rules-modules/` or via `PersistentStorage`.

## When to ask the user

- About to deploy a rule to a controller that's currently running customer automation — confirm the deploy window (rule save = engine reload = a few seconds of skipped triggers).
- A rule needs to call out to an external service (Telegram, email, REST) on a regular schedule — confirm the user expects the network load and side effects.
- A virtual device the rule defines would shadow an existing real device — confirm renaming vs intentional override.
- The rule modifies physical outputs (relays, dimmers) based on conditions — confirm the safe state on engine startup / reload.
- Migrating a rule from one controller to another — confirm slave_id / device-name assumptions hold on the target.
