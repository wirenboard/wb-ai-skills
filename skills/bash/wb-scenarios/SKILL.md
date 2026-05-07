---
name: wb-scenarios
description: Wiren Board web UI scenarios (`wb-scenarios`) — declarative rules without code. devicesControl, lightControl, thermostat, schedule. Config /etc/wb-scenarios.conf.
allowed-tools: Bash Read Write WebFetch
---

# scenarios

`wb-scenarios` is a separate engine on top of `wb-rules` that generates JS rules from declarative JSON in `/etc/wb-scenarios.conf`. It's the "no-code" layer for typical tasks: device group control, motion-activated lighting, thermostat, schedule.

Load this on: "make a scenario", "set up thermostat", "light by motion sensor", "turn off on schedule", `wb-scenarios.conf`, "scenarios in web UI".

**Don't confuse with `/wb-rules`** (full JS, ES5, defineRule). Scenarios are a simplified add-on for typical cases. If the task is non-standard or computations are needed — go to wb-rules.

## Architecture

```
/etc/wb-scenarios.conf   (via confed, JSON)
       │
       ▼
wb-scenarios-reloader.service
       │ (generates .js under the hood)
       ▼
/etc/wb-rules/<generated rules>
       │
       ▼
wb-rules engine
```

Service: `wb-scenarios-reloader` (NOT `wb-scenarios.service` — that doesn't exist).

Schema: `/usr/share/wb-mqtt-confed/schemas/wb-scenarios.schema.json` — describes 4 scenario types and UI.

## Four scenario types

### 1. `devicesControl` — group control

"When control A changes → set controls B and C". Basic automation.

```json
{
  "scenarioType": "devicesControl",
  "name": "Hallway light",
  "id_prefix": "corridor_light",
  "enable": true,
  "inControls": [
    {"deviceId": "wb-mwac_25", "controlId": "Input 1"}
  ],
  "outControls": [
    {"deviceId": "wb-mr6c_2", "controlId": "K1", "value": true}
  ]
}
```

`inControls` — triggers (value change), `outControls` — what to set with what value.

### 2. `lightControl` — lighting

Activation by motion sensor with off-timer, night mode, dimming.

```json
{
  "scenarioType": "lightControl",
  "name": "Bathroom light",
  "id_prefix": "wc_light",
  "enable": true,
  "motionSensor": {"deviceId": "wb-msw-v4_20", "controlId": "Motion"},
  "lightOutput": {"deviceId": "wb-mr6c_2", "controlId": "K2"},
  "delayOff": 60,
  "ambientLightSensor": {"deviceId": "wb-msw-v4_20", "controlId": "Illuminance"},
  "darkThreshold": 100
}
```

### 3. `thermostat` — thermostat

Heater on by setpoint - current diff with hysteresis.

```json
{
  "scenarioType": "thermostat",
  "name": "Living room",
  "id_prefix": "living_room",
  "enable": true,
  "temperatureSensor": {"deviceId": "wb-msw-v4_20", "controlId": "Temperature"},
  "heaterOutput": {"deviceId": "wb-mr6c_2", "controlId": "K3"},
  "setpoint": 22.0,
  "hysteresis": 0.5
}
```

### 4. `schedule` — schedule

"Every day at HH:MM do X". Under the hood — wb-rules cron.

```json
{
  "scenarioType": "schedule",
  "name": "Watering",
  "id_prefix": "watering",
  "enable": true,
  "schedule": {"hour": 6, "minute": 30, "days": [1,2,3,4,5,6,7]},
  "actions": [
    {"deviceId": "wb-mr6c_2", "controlId": "K4", "value": true},
    {"deviceId": "wb-mr6c_2", "controlId": "K4", "value": false, "delay": 1800}
  ]
}
```

`days` — `[1..7]` (1=Mon … 7=Sun). `delay` — delay after the previous action (sec).

## Basic commands

```bash
ssh root@<HOST> 'cat /etc/wb-scenarios.conf'                                # current
ssh root@<HOST> 'systemctl status wb-scenarios-reloader --no-pager'         # status
ssh root@<HOST> 'journalctl -u wb-scenarios-reloader -n 30 --no-pager'      # logs
ssh root@<HOST> 'ls /etc/wb-rules/wb-scenario-*.js 2>/dev/null'             # generated .js
```

After editing the config, `wb-scenarios-reloader` recreates rules and restarts `wb-rules`.

## Edit via confed (recommended path)

```bash
ssh root@<HOST> 'CID=ai-$(date +%s); mosquitto_sub -t "/rpc/v1/confed/Editor/Save/$CID/reply" -C 1 -W 10 & sleep 0.2; \
  PAYLOAD=$(jq -nc --rawfile c /tmp/scenarios.conf.new "{id:1,params:{path:\"/etc/wb-scenarios.conf\",content:(\$c|fromjson)}}"); \
  mosquitto_pub -t "/rpc/v1/confed/Editor/Save/$CID" -m "$PAYLOAD"; wait'
```

`content` is a **JSON object**, not a string (see `/wb-mqtt-serial`, same format).

## Direct file editing

You can use `wb_write_file` or `cat >`, but **must** reload the generator:

```bash
ssh root@<HOST> 'systemctl restart wb-scenarios-reloader'
```

Via confed — restart is automatic; via direct edit — manual.

## When the scenario isn't enough — go to wb-rules

- The condition depends on multiple controls simultaneously with logic.
- A computed value is needed (average, asymmetric hysteresis, PID).
- State is needed (counters, "N times in a row" trigger).
- Timers other than schedule (interval, exponential delay) are needed.
- Virtual devices.

Scenarios are good for "press button → turn on relay" and "by timer turn on/off". Beyond that — wb-rules.

## Pitfalls

- **`wb-scenarios.service` doesn't exist** — the service is called `wb-scenarios-reloader`.
- **Duplicate id_prefix** — two scenarios with the same `id_prefix` will generate overlapping rule names, conflict.
- **Direct editing of `/etc/wb-rules/wb-scenario-*.js`** — overwritten on next reload. Only via `wb-scenarios.conf`.
- **Cyrillic in `id_prefix`** — schema forbids (regex `^[0-9a-zA-Z_]+$`). In `name` — fine.
- **Scenario didn't appear in web UI** — check `journalctl -u wb-scenarios-reloader` for parse errors. Broken config — web UI shows nothing.
- **Scenario and an analogous wb-rules rule** — conflict (both write to one control). Don't duplicate.
- **`schedule` without timezone** — uses the system one (`timedatectl`). After timezone upgrade scenarios may "shift".

## Documentation

- WB wiki — scenarios: <https://wirenboard.com/wiki/Wb-scenarios>
- Schema: `/usr/share/wb-mqtt-confed/schemas/wb-scenarios.schema.json` on the controller.
