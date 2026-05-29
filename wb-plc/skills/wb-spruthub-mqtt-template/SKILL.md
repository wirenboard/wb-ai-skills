---
name: wb-spruthub-mqtt-template
description: "Create a SprutHub MQTT template (JSON) for a Wiren Board device from its wb-mqtt-serial template and sprut.ai catalog entry. Use when user asks to create a SprutHub template for a device model, add a template for <WB-XXX>, or generate a HomeKit integration."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# SprutHub MQTT template generator

## When to load this skill

Load when the task involves creating or working with SprutHub HomeKit integrations for Wiren Board devices:

- "Create a SprutHub template for device X"
- "Add HomeKit support for WB-DALI3" / "WB-MR6" / other WB model
- "Generate a JSON template from wb-mqtt-serial config"
- "Integrate device with sprut.ai catalog"
- "Create template for custom Modbus device"

**Do NOT load** for:
- Configuring existing devices on the bus → use `/wb-serial` (Modbus) or `/wb-zigbee` (Zigbee)
- Authoring wb-mqtt-serial Jinja templates themselves → use `/wb-serial`
- Writing a custom daemon or HomeKit bridge → use `/wb-dev`

## Output: file naming and location

Generates JSON templates named like `WB-MWAC.json` or `WB-UPSv3.json`. **File location**: if the repository has an `mqtt/` subdirectory, place it there (following `wirenboard/wb-spruthub-templates`); otherwise place in root. On controller deployment, the path is always `/mnt/data/makesimple/.SprutHub/data/Templates/MQTT/` regardless of repo location.

## What we need from the user

1. **Device model** (`WB-XXX`).
2. **catalogId** — search with escalation:
   1. If user provides a **number** — use it directly.
   2. If user provides a **link** to https://sprut.ai/catalog/item/... — `WebFetch`, search for `ID: <number>` in the "Data" section.
   3. If nothing provided — **search ourselves** in the Wiren Board catalog: https://sprut.ai/catalog?tags=WirenBoard, find the device card by model name, open it, extract `ID`. Catalog has pagination — check `?page=2,3,...` if not on first page.
   3a. **Slug guessing**: if not found in catalog pages — try direct URL `https://sprut.ai/catalog/item/<slug>` by analogy with similar model. Example: found v.2 as `modul-bespereboynogo-pitaniya-wb-ups-v-2` → try `...-v-3` for v.3.
   4. If slug doesn't work — ask user for the device card link.
   5. If user has **no link either** — direct them to "WB + SprutHub templates" Telegram group to request `catalogId` from SprutHub team. Don't write template without `catalogId` (or write it but warn that the field is missing, like `Power_status.json`).
3. **Scope** — which services to make visible (`visible: true`), which to hide. Default: one main service visible, others `visible: false`.

Ask about these **before** opening files.

## Finding MQTT channels

Source selection depends on device type. For **wb-m\* modules** (WB-MWAC, WB-MR6, WB-MAI6, WB-UPS v.3, etc. — anything handled by wb-mqtt-serial), Jinja templates and real MQTT are equivalent: wb-mqtt-serial publishes names/types/units **directly from the template** when creating the device, before the first Modbus poll. For everything else (system topics, GPIO, zigbee2mqtt), there's no Jinja — check live MQTT.

### 1. Jinja wb-mqtt-serial — primary for wb-m\* modules

In order of preference:

1. **Upstream**: `https://raw.githubusercontent.com/wirenboard/wb-mqtt-serial/master/templates/config-<device>.json.jinja` — source of truth.
2. **On controller via SSH**: `/usr/share/wb-mqtt-serial/templates/config-<device>.json` — already rendered, no Jinja variables. Use if creating a template **for a specific user's WB** and suspect the package version lags upstream.

From Jinja, read:

- `device.id` — MQTT id prefix. **Take as-is** — some modules use hyphens (`wb-mai6`), some underscores (`wb_ups_v3`). Don't guess.
  - ⚠ One Jinja file may serve **multiple product names** via `hw[].signature` array. Example: `config-wb-dali.json.jinja` works for WB-DALI, WB-MDALI, and WB-DALI3 (product name on website, but `device.id = wb-dali`). The `model` field in SprutHub template is the user-facing name (`WB-DALI3`); `device.id` in `modelId` is what's in Jinja (`wb-dali`).
- `channels[].name` → MQTT topic name. Final path: `/devices/<device.id>_<modbus_addr>/controls/<name>`.
- `channels[].enabled` — if `false`, channel won't appear in MQTT until user enables it in web UI. Don't include such channels in SprutHub template unless explicitly requested.
- `channels[].type` — primary marker for mapping to SprutHub service.
- `units`, `format` (`s16`/`u32`), enum (`enum` + `enum_titles`) — details.
- `channels[].mqtt_id` — **if present, overrides the topic name**. Use it instead of `name` when building `topicGet`/`topicSet`.
- `channels[].condition` — channel appears in MQTT only if condition is met (usually firmware version `fw`). Include in SprutHub template carefully.

### 2. Live MQTT on controller — primary for non-Modbus, verification for wb-m\*

Required for devices **without Jinja template**: `power_status`, `hwmon`, `system`, `buzzer`, `wb-gpio`, wb-rules devices, zigbee2mqtt, etc. Also for verifying package version or `condition` channel behavior if uncertain.

Ask user for controller IP. Then:

```bash
# 1. Find device id (short dump of all names, auto-exits in 3 sec):
mosquitto_sub -h <wb-ip> -t '/devices/+/meta/name' -v -W 3

# 2. All controls of specific device with values:
mosquitto_sub -h <wb-ip> -t '/devices/<id>/controls/+' -v -W 3

# 3. Meta of each control — type/units/readonly/min/max/order:
mosquitto_sub -h <wb-ip> -t '/devices/<id>/controls/+/meta' -v -W 3
```

**Always use** `-W <seconds>` or `-C <N>` — without it subscription hangs indefinitely.

From meta `type` (`switch` / `value` / `temperature` / `voltage` / `current` / `power` / `pushbutton` / `text` / `wo-switch` / `range`), you can immediately see the correct SprutHub service.

### 3. Services on top of wb-mqtt-serial (wb-mqtt-dali, etc.)

A separate class — Python daemons that call wb-mqtt-serial over MQTT-RPC and publish **their own `/devices/{id}/controls/...` set**. Example: `wb-mqtt-dali` — for one physical WB-DALI3, publishes two layers:
- `/devices/wb-dali_<addr>/...` — the hardware itself (via wb-mqtt-serial from Jinja);
- `/devices/<gateway_device_id>_bus_<N>_<short>/...` — each DALI lamp behind the gateway, with controls `wanted_level`, `actual_level`, `dapc`, `off`, `up`/`down`, `step_up`/`step_down`, `recall_*`, `go_to_scene`, `error_status` (see `wb/mqtt_dali/dali_controls.py`);
- `/devices/<gateway_device_id>_bus_<N>_dali2_<short>/...` — DALI 2 input devices (sensors/buttons) with per-instance controls `occupied{N}`/`movement{N}`/`illuminance{N}`/`button{N}`/`long_press{N}`/`short_press{N}`/`double_press{N}` (see `dali2_controls.py`).

Source of truth — the service's own repository. Find controls:

```bash
gh api "repos/wirenboard/wb-mqtt-dali/contents/wb/mqtt_dali" \
  | python3 -c 'import json,sys; [print(d["name"]) for d in json.load(sys.stdin)]'
# then raw-fetch specific file and grep for MqttControl(/ControlInfo(
```

Specifics:
- Service `device.id` is often **user-configurable** (in `/etc/wb-mqtt-<srv>.conf`). Can't anchor `modelId` to a fixed prefix — use broad `([a-zA-Z0-9_-]+)` plus anchor on service-unique control (e.g., `wanted_level` for DALI lamps, `_dali2_` segment in device_id + `occupied[0-9]+` for DALI 2 sensors).
- One physical device (WB-DALI3) usually needs **a set** of SprutHub templates: for the gateway itself + for each class of devices behind it (lamp, occupancy, light sensor, button).
- `catalogId` for derived templates (lamps behind gateway, DALI 2 sensors) — **omit it**, like in `Power_status.json`: these devices aren't from Wiren Board catalog, they have no card.

### 4. Wiren Board Wiki — semantics only

`https://wiki.wirenboard.com/wiki/<Device>` and `<Device>_Registers`.

Wiki describes **Modbus registers**, not MQTT topics. Use only to understand "what does value 3 in this enum mean", "which channel is primary from user's perspective". Don't copy topic names from Wiki.

### If device doesn't exist anywhere (custom, prototype)

Ask user to provide output from `mosquitto_sub -h <wb-ip> -t '/devices/#' -v -W 5` — that's enough to build the template.

## WB control → SprutHub service mapping

| WB control (by units/meaning) | service.type | characteristic.type | link.type |
|---|---|---|---|
| `%` (battery charge) | `BatteryService` | `BatteryLevel` | `Integer` |
| charging state enum | `BatteryService` | `ChargingState` | `Integer` ⚠ see below |
| `V` | `C_VoltMeter` | `C_Volt` | `Double` |
| `A` | `C_AmpereMeter` | `C_Ampere` | `Double` |
| `deg C` | `TemperatureSensor` | `CurrentTemperature` | `Double` (+`minStep: 0.1..0.5`) |
| `%` humidity | `HumiditySensor` | `CurrentRelativeHumidity` | `Double` |
| `lux` | `LightSensor` | `CurrentAmbientLightLevel` | `Double` |
| switch (RW) relay type | `Switch` or `Outlet` | `On` | `Boolean` (needs `topicSet: .../on`) |
| switch (RO) — discrete input | `ContactSensor` | `ContactSensorState` | `Integer` |
| switch (RO) — motion | `MotionSensor` | `MotionDetected` | `Integer` |
| switch (RO) — occupancy | `OccupancySensor` | `OccupancyDetected` | `Integer` |
| `value` — click/pulse counter | `C_PulseMeter` | `C_PulseCount` | `Double` |
| value 0..N% / range without separate On topic (analog output, DALI `wanted_level`) | `Lightbulb` (**only** `Brightness`, **no** `On`) | `Brightness` | `Integer` (SprutHub treats non-zero as "on") |
| valve/damper | `Valve` | `Active` | `Integer` |
| pushbutton (RW) | via `Switch.On` + rules | — | — |

For analog sensors, **always** set `checkValue: true` — discards NaN/empty from wb-mqtt-serial.

**Channels that DON'T map to HomeKit — skip**:

- `type: "text"` (e.g., `Serial`, `FW Version`, `HW Batch Number`) — HomeKit has no characteristic for arbitrary strings.
- Enum channels with no HomeKit equivalent (e.g., `Temperature Status` with 5 states "ok / low / charge-only / overheat …"). Don't force as `Integer` into random characteristic — creates visual clutter.
- `pushbutton` without clear semantic meaning (diagnostic `Restart Charge`, etc.) — leave for user to handle via wb-rules.
- Controls with `retain=false` (value not stored in broker — published as event then lost). Examples in wb-mqtt-dali: `short_press{N}`, `double_press{N}`. Don't work as state sensors (SprutHub won't get retained value on restart). Trigger these events via wb-rules / SprutHub scenarios, not template.

If no channels map meaningfully — this signals incomplete template; clarify with user what device data should reach HomeKit.

## File format (current)

```json
{
  "manufacturer": "Wiren Board",
  "model": "WB-XXX",
  "modelId": "/devices/(<device_id>_[0-9]{1,3})/controls/<unique-control>/meta",
  "name": "Human-readable name",
  "catalogId": <number>,
  "services": [
    {
      "name": "...",
      "type": "<ServiceType>",
      "visible": true,
      "characteristics": [
        {
          "type": "<CharType>",
          "link": [
            {
              "type": "<Boolean|Integer|Double|String>",
              "topicGet": "/devices/(1)/controls/<Name>",
              "topicSet": "/devices/(1)/controls/<Name>/on"
            }
          ]
        }
      ]
    }
  ]
}
```

**Rules (current, from upstream docs):**

- `manufacturer` — **always `"Wiren Board"`**. No other values in upstream repo (~120 templates) — even for obviously third-party hardware: DS18B20 in `1-wire.json`, third-party DALI ballasts in `DALI_Lamp.json`/`DALI2_*.json`, Linux sensors in `Hwmon.json`. Convention semantic: "published through Wiren Board stack", not "manufactured by Wiren Board". Display-only field, doesn't affect functionality.
- `model` — for **specific WB products** use marketing name (`"WB-DALI3"`, `"WB-MR6"`). For **generalized classes** (multiple vendors behind one protocol, system services) use class name as in upstream: `"System"` (Power_status/Hwmon/Buzzer), `"1-wire"` (any 1-wire sensor), `"DALI Gear"` (any DALI ballast via wb-mqtt-dali). Use terminology from service spec/docs (DALI: "gear" = control gear, not "lamp").
- For templates **on top of daemon services** (wb-mqtt-dali, zigbee2mqtt, ...) — **mirror service nomenclature**. Example: `wb/mqtt_dali/dali_device.py:139` sets `default_name_prefix = "DALI"` (no version), `dali2_device.py:687` sets `"DALI-2"` (hyphenated). In the upstream templates, `model` is `"DALI Gear"` and `"DALI-2 Occupancy Sensor"` — matching exactly. This convention isn't invented; extract it from service sources.
- `link` — **always an array**, even with one element.
- `template` (value transformations) — field exists in docs but **never used in upstream repo (~120 templates)**. If it seems needed — almost certainly isn't: pick service.type/characteristic.type so SprutHub converts natively (see `WBIO-AO-10V-8.json` — Brightness without On instead of transforming 0..100 → bool).
- `modelId`, `manufacturerId` — **no outer parentheses** for alternation: `"_TZ3000_a|_TZ3000_b"`, not `"(_TZ3000_a|_TZ3000_b)"`.
- Value type — **`Double`**, not `Float` (Float removed 2024-04-17).
- In `modelId`, parentheses `(...)` are capture groups; referenced as `(1)`, `(2)` in `topicGet`/`topicSet`. Two patterns:
  - **literal-capture** — `(2)` captures **entire matched control** (`(IN [0-9]{1,2}.?[PN]* Temperature)` → `IN 1 Temperature`). Use when you need one service per matched channel with no linked topics. Example: `WB-MAI6_Temperature.json`.
  - **digit-capture** — `(2)` captures **index only** (`K([0-9]{1,2})` → `1`). Use when you need to gather **related** topics of same index in one template: `K(2)`, `Input (2)`, `Channel (2)`, `Bus (2) State` + `Bus (2) Powered` + `Bus (2) Overheat`. Examples: `WB-MR6.json`, `WB-DALI3.json`.
- `topicSet` needed **only** for RW controls; omit for RO.

## Good reference templates in repo

- `mqtt/WBMZ4-BATTERY.json` — BatteryService + Ampere/Volt.
- `mqtt/Power_status.json` — ContactSensor + VoltMeter, no `catalogId` (OK to omit).
- `mqtt/Hwmon.json` — multiple TemperatureSensor from one device.
- `mqtt/WB-MS.json` — Temp/Humidity/Light on one device.
- `mqtt/WB-MAI6_Temperature.json` — example of literal-capture `(2)` in `topicGet`.
- `mqtt/WB-MR6.json` — example of digit-capture `K([0-9]{1,2})` with related `K(2)` + `Input (2)`.
- `mqtt/WB-MR3_Input.json` — `ContactSensor` + 5 `C_PulseMeter`/`C_PulseCount` (state + 4 click counters); canonical set for input with counters.
- `mqtt/WBIO-AO-10V-8.json` — Lightbulb with only `Brightness` (no `On`) for 0..N analog output. Same pattern fits DALI `wanted_level`.

Before writing — open 1–2 similar templates as reference.

## Workflow

1. Clarify **model**, **catalogId** (or link to sprut.ai), **service set**.
2. Download/read wb-mqtt-serial Jinja template. Extract `device.id` and channel list with `enabled != false` (plus any explicitly requested "disabled" channels).
3. If catalogId given as link — `WebFetch` the sprut.ai card, search for "ID: <number>".
4. Build service list: main → `visible: true`, diagnostics → `visible: false`.
5. Write JSON. Path: if `mqtt/` exists in repo root, put there; otherwise root. Name like `WB-XXX.json` / `WB-XXXv3.json`.
6. Validate with `python3 -m json.tool <file> > /dev/null`.
7. Point out to user:
   - **enum conflicts** between WB and HomeKit (e.g., WB battery status 0..4 vs HomeKit ChargingState 0..2) — without `template` transforms, HomeKit icons/states will show wrong values;
   - **signed currents** (`s16`) — display as-is with sign, that's normal;
   - **deployment**: `scp <file>(s) root@<wb>:/mnt/data/makesimple/.SprutHub/data/Templates/MQTT/` (multiple files: `scp *.json root@...`) → web UI 7777 → Settings → Advanced → "Reload templates" → Controllers → create MQTT controller → wait for device; if issues — Controllers → ⋯ → "Debug".

## What NOT to do

- Don't guess `device.id` by analogy — WB modules use both hyphens and underscores. Read Jinja.
- Don't assume product name (`WB-DALI3`) equals `device.id` (`wb-dali`) — one Jinja file often serves multiple marketing names via `hw[].signature`.
- Don't use single object in `link` — array only.
- Don't write `"Float"`.
- Don't set `catalogId: 0` or garbage values — omit the field and ask user to find it (Power_status.json in repo works without it).
- Don't include `enabled: false` channels from Jinja unless explicitly requested — they won't publish in MQTT and template will look "half-broken" in SprutHub.
- Don't stuff `text` channels (`Serial`, `FW Version`, ...) and unmarked enums into random characteristics — skip them (see rule above).
- Don't run `mosquitto_sub` without `-W` or `-C` — subscription will hang and block the session.
