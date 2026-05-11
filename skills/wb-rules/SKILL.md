---
name: wb-rules
description: "Wiren Board rules engine. ES5 JavaScript in /etc/wb-rules/*.js. defineRule, defineVirtualDevice, PersistentStorage, timers, cron. Load for automation tasks."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-rules

Automation engine on the controller. Scripts in `/etc/wb-rules/*.js`, modules in `/etc/wb-rules-modules/*.js`. Language — **ES5** (no let/const/arrow). Manage rules via `wb-cli rules` on the controller.

Canonical docs: <https://github.com/wirenboard/wb-rules>. When in doubt — `WebFetch` the README.

## Rule operations via wb-cli

```bash
ssh root@<HOST> wb-cli rules list
ssh root@<HOST> wb-cli rules load myrule
ssh root@<HOST> 'wb-cli rules save myrule "$(cat /tmp/rule.js)"'
ssh root@<HOST> wb-cli rules disable myrule
ssh root@<HOST> wb-cli rules delete myrule
```

Rule names — without `.js`. After save, check logs:
```bash
ssh root@<HOST> journalctl -u wb-rules --since '10s ago' --no-pager
```

## Workflow

1. Check channel type: `ssh root@<HOST> wb-cli devices controls <device>`
2. List existing rules: `ssh root@<HOST> wb-cli rules list`
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

## Pitfalls

- **switch = true/false, NOT 0/1**
- **Check logs after every save** — errors are silent otherwise
- **whenChanged on own output** — infinite loop
- **Side effects in when/asSoonAs condition** — forbidden
- **Globals don't cross files** — use modules or PersistentStorage
- **cron 5 fields = almost certainly a bug** — prepend `0` for seconds
- **`ps["obj"].foo = 5` without StorableObject** — won't persist
- **Names with hyphens via dot notation** — SyntaxError
