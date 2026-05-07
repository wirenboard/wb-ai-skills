---
name: scenarios
description: Wiren Board Web UI scenarios (`wb-scenarios`) via MCP — devicesControl, lightControl, thermostat, schedule. /etc/wb-scenarios.conf via confed.
allowed-tools: Bash Read Write WebFetch
---

# scenarios (MCP)

Declarative Web UI scenarios (`wb-scenarios`) via `wb_confed_*`. 4 types: `devicesControl`, `lightControl`, `thermostat`, `schedule`. Under the hood they compile into wb-rules JS.

Load this when: "make a scenario", "configure a thermostat", "light by motion sensor", "by schedule", `wb-scenarios.conf`, "scenarios in Web UI".

**Don't confuse with `/wb-rules`** (full JS). Scenarios are a simplified add-on for typical cases.

## Tool routing

| Intent | Tool |
|--------|------|
| Current scenarios config | `wb_confed_load path=/etc/wb-scenarios.conf` |
| Save new config (validation + reload) | `wb_confed_save path=/etc/wb-scenarios.conf content=<JSON object>` |
| Generator status | `wb_systemd_unit unit=wb-scenarios-reloader` |
| Generator logs | `wb_logs unit=wb-scenarios-reloader since="10m ago"` |
| Generated .js under the hood | `wb_ssh_exec` `ls /etc/wb-rules/wb-scenario-*.js` |

## Four scenario types

### `devicesControl` — group control

"Control A changed → set controls B and C".

```json
{"scenarioType":"devicesControl","name":"...","id_prefix":"...","enable":true,
 "inControls":[{"deviceId":"wb-mwac_25","controlId":"Input 1"}],
 "outControls":[{"deviceId":"wb-mr6c_2","controlId":"K1","value":true}]}
```

### `lightControl` — lighting

Motion sensor + output + delayOff. Optionally: light sensor + threshold.

```json
{"scenarioType":"lightControl","name":"...","id_prefix":"...","enable":true,
 "motionSensor":{"deviceId":"wb-msw-v4_20","controlId":"Motion"},
 "lightOutput":{"deviceId":"wb-mr6c_2","controlId":"K2"},
 "delayOff":60,
 "ambientLightSensor":{"deviceId":"wb-msw-v4_20","controlId":"Illuminance"},
 "darkThreshold":100}
```

### `thermostat` — thermostat

Setpoint + hysteresis + sensor + output.

```json
{"scenarioType":"thermostat","name":"...","id_prefix":"...","enable":true,
 "temperatureSensor":{"deviceId":"wb-msw-v4_20","controlId":"Temperature"},
 "heaterOutput":{"deviceId":"wb-mr6c_2","controlId":"K3"},
 "setpoint":22.0,"hysteresis":0.5}
```

### `schedule` — schedule

"At HH:MM on weekdays — perform actions".

```json
{"scenarioType":"schedule","name":"...","id_prefix":"...","enable":true,
 "schedule":{"hour":6,"minute":30,"days":[1,2,3,4,5,6,7]},
 "actions":[
   {"deviceId":"wb-mr6c_2","controlId":"K4","value":true},
   {"deviceId":"wb-mr6c_2","controlId":"K4","value":false,"delay":1800}
 ]}
```

`days`: `[1..7]` (1=Mon). `delay`: after the previous action (sec).

## Scenario: add a new one

1. `wb_confed_load path=/etc/wb-scenarios.conf` — current object.
2. Add an object to the `scenarios` array.
3. `wb_confed_save path=/etc/wb-scenarios.conf content=<full object>`.
4. `wb_systemd_unit unit=wb-scenarios-reloader` — status (`active`).
5. `wb_logs unit=wb-scenarios-reloader since="1m ago"` — no errors?
6. Verify operation — change `inControls` via `wb_mqtt_write` or wait for the schedule.

## When a scenario isn't enough — `/wb-rules`

- Condition over multiple controls simultaneously with logic.
- A computed quantity (average, asymmetric hysteresis, PID).
- State (counters, "N times in a row").
- Custom timers (interval, exponential backoff).
- Virtual devices.

## Gotchas

- **`wb-scenarios.service` doesn't exist** — it's `wb-scenarios-reloader`.
- **Duplicate `id_prefix`** — generated rule name collisions.
- **Direct edits to `/etc/wb-rules/wb-scenario-*.js`** — overwritten on reload.
- **Cyrillic in `id_prefix`** — schema forbids it.
- **Scenario and wb-rules conflict** — both writing to the same control.
- **`schedule` uses system timezone** — `timedatectl` must be correct.

## Related skills

- `/wb-rules` — when a scenario doesn't cover.
- `/wb-mqtt-serial` — adding new devices for inControls/outControls.

Details (format, schema constraints) — bash-flavor twin `/scenarios`.

## Documentation

- WB wiki: <https://wirenboard.com/wiki/Wb-scenarios>
