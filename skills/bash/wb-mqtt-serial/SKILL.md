---
name: wb-mqtt-serial
description: "Modbus/RS-485 driver on a Wiren Board controller. Config /etc/wb-mqtt-serial.conf, templates, access via MQTT RPC. Enabling/disabling channels, adding devices, scanning the bus, editing wb-mqtt-serial configuration."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-mqtt-serial

Modbus/RS-485 driver. Config `/etc/wb-mqtt-serial.conf`, templates `/usr/share/wb-mqtt-serial/templates/` (packaged, don't touch) and `/etc/wb-mqtt-serial.conf.d/templates/` (your own). Access via MQTT RPC `wb-mqtt-serial/...`, not via files. Load this on: "channel not publishing", "don't see device on the bus", "polling stalled", "enable channel X", "scan the bus", "slave_id / holding / coil / input register", enabling/disabling channels, adding/removing/editing devices in the wb-mqtt-serial config, "add a Modbus device", "remove a device", "clear device list", "edit serial config", "wb-mqtt-serial.conf", editing ports/devices in the config.

**Skill boundary:** if a template needs to be created for a device that isn't among the built-ins — that's the `wb-mqtt-serial-template` skill. If the issue is signal/CRC/timeouts — `troubleshooting-serial`.

**HOST variable:** in all examples below `<HOST>` means `wirenboard-<SN>.local`, where `<SN>` is the serial number (e.g. `wirenboard-AABBCCDD.local`). Substitute the real address.

## RPC and files — what to take from where

| What | From | Why |
|-----|--------|--------|
| All device channels, including `enabled:false` | **File** `/usr/share/wb-mqtt-serial/templates/config-<device.id>.json` | On current firmwares (wb-2602, wb-2507) `templates/GetTemplate` RPC **doesn't work** (timeout), and `device/LoadConfig` returns only `{fw, model, parameters}` without channels |
| Current driver config | RPC `config/Load` | |
| Device firmware parameters (debounce, modes, in/out mappings) | RPC `device/LoadConfig` | Only `{fw, model, parameters}` |
| RS-485 port parameters | RPC `ports/Load` | |
| Writing the config | RPC `confed/Editor/Save` | Validation + atomic restart. Broken JSON isn't written, bus polling stays alive |
| Bus scanning | RPC `wb-device-manager/bus-scan/Start` (async, progress/devices in retained `/wb-device-manager/state`) | `scan_type:"extended"` — Fast Modbus, `"standard"` — regular. The old `wb-mqtt-serial/port/Scan` silently misses live WB devices (bug observed on WB-MAP6S) |
| Pinpoint slave_id check | RPC `device/Probe` | |

Direct `ssh ... cat >` to a `.conf` — only with a backup and deliberately (see below).

- **"Channel not in MQTT" ≠ "not supported."** Many template channels are `"enabled": false` (Uptime, Counter, Total, Serial). First read the template, then conclude.
- **Look for the template on the controller, not on GitHub.** On the hardware — it matches the firmware. `WebFetch` for templates is almost always a waste.
- **Custom template — last resort.** First check the built-in.
- **Scan is async.** `wb-device-manager/bus-scan/Start` returns immediately, watch progress in retained state.

## MQTT RPC via Bash

The MQTT RPC pattern on the controller — subscribe to reply, publish the request:

```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/<driver>/<service>/<method>/$CID/reply" -C 1 -W <timeout> & sleep 0.2; mosquitto_pub -t "/rpc/v1/<driver>/<service>/<method>/$CID" -m '"'"'{"id":1,"params":{...}}'"'"'; wait'
```

`params` is a nested object, mandatory field (even an empty `{}`).

### Getting the device channel list (via file)

Find the device template by `device_type` (e.g. `WB-MR6C`):

```bash
# File name = config-<device.id>.json, where device.id is a field from the template.
# Simple case: WB-MR6C → wb-mr6c. Complex (with spaces/dots): "WB-MR6C v.3" → wb-mr6cv3.
# Most reliable way — find by device_type field:
ssh root@<HOST> 'for f in /usr/share/wb-mqtt-serial/templates/*.json; do dt=$(jq -r ".device_type" "$f" 2>/dev/null); if [ "$dt" = "WB-MR6C" ]; then echo "$f"; break; fi; done'
```

Read channels:

```bash
ssh root@<HOST> 'jq ".device.channels[] | {name, enabled}" /usr/share/wb-mqtt-serial/templates/config-wb-mr6c.json'
# or the whole template:
ssh root@<HOST> 'cat /usr/share/wb-mqtt-serial/templates/config-wb-mr6c.json'
```

Template structure: `{title, device_type, group, hw, device:{name, id, channels:[...], parameters:[...], groups:[...], translations:{}}}`.

### RPC call examples

**Device firmware parameters (debounce, modes, mappings) — NOT channels:**
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/device/LoadConfig/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/device/LoadConfig/$CID" -m '"'"'{"id":1,"params":{"device_id":"wb-mr6c_138"}}'"'"'; wait'
```

Returns `{fw, model, parameters}`. For WB-MR6C `parameters` is `in0_mode`, `in0_debounce_ms`, `in1_out1_sp`, etc. **No channels in the response** — for channels read the template file (see above).

**Current driver config:**
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/config/Load/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/config/Load/$CID" -m '"'"'{"id":1,"params":{}}'"'"'; wait'
```

**Save config (validation + restart):**

⚠️ **Critical:** `content` is a **JSON object**, not a serialized string. If you pass a string (with escaped quotes inside), `confed/Editor/Save` writes it to the file literally as a `"{...}"` literal, and `wb-mqtt-serial` falls over with `requires objectValue`, halting polling of the **entire bus** until restored from backup.

```bash
# Prepare the new config locally on the controller as a file:
ssh root@<HOST> 'cp /etc/wb-mqtt-serial.conf /tmp/wb-mqtt-serial.conf.new'
# … edit /tmp/wb-mqtt-serial.conf.new any way (jq, sed, awk) …

# Save via RPC: jq -Rs reads the file raw and puts it as JSON string in the field, then fromjson turns it into an object:
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); PAYLOAD=$(jq -nc --rawfile c /tmp/wb-mqtt-serial.conf.new "{id:1,params:{path:\"/etc/wb-mqtt-serial.conf\",content:(\$c|fromjson)}}"); mosquitto_sub -t "/rpc/v1/confed/Editor/Save/$CID/reply" -C 1 -W 15 & sleep 0.2; mosquitto_pub -t "/rpc/v1/confed/Editor/Save/$CID" -m "$PAYLOAD"; wait'
```

Key part of the payload — `content:($c|fromjson)`: jq takes the file content as an **object**, not as a string. Without `fromjson` (i.e. `content:$c` or direct substitution `"content":"..."`) — you get bus-down.

After Save, verify the file became an object, not a string:

```bash
ssh root@<HOST> 'head -c 50 /etc/wb-mqtt-serial.conf'
# OK:    {\n    "debug" : false,\n    "ports" ...
# Bad:   "{\\n    \\"debug\\": ...    ← shouldn't be like this
```

If it became a string — immediately roll back from backup.

**Bus scan (via `wb-device-manager`, async):**

```bash
# Start (returns immediately)
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-device-manager/bus-scan/Start/$CID/reply" -C 1 -W 10 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-device-manager/bus-scan/Start/$CID" -m '"'"'{"id":1,"params":{"scan_type":"extended","preserve_old_results":false,"port":{"path":"/dev/ttyRS485-1","baud_rate":115200,"parity":"N","data_bits":8,"stop_bits":2}}}'"'"'; wait'

# Polling progress from retained-state
ssh root@<HOST> 'for i in $(seq 1 60); do
  s=$(mosquitto_sub -t /wb-device-manager/state -C 1 -W 2)
  echo "$s" | jq -r ".scanning, .progress" | xargs echo
  echo "$s" | jq -e ".scanning == false" >/dev/null && break
  sleep 2
done'

# Final devices
ssh root@<HOST> 'mosquitto_sub -t /wb-device-manager/state -C 1 -W 3 | jq ".devices"'
```

`scan_type:"extended"` — Fast Modbus (WB+Onokom, seconds). `scan_type:"standard"` — regular Modbus (slower, but sees third-party). Iterating bauds — repeat Start with other parameters and `preserve_old_results:true`.

**Don't use the old `wb-mqtt-serial/port/Scan`** — it silently misses live WB devices (observed on WB-MAP6S). If something wasn't found via `bus-scan` — check pinpoint with `device/Probe`.

**Pinpoint slave_id check:**
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/device/Probe/$CID/reply" -C 1 -W 10 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/device/Probe/$CID" -m '"'"'{"id":1,"params":{"path":"/dev/ttyRS485-1","baud_rate":9600,"slave_id":138}}'"'"'; wait'
```

Other: `device/Load` — live channel values; `device/Set` — write `{"channel_name": value}` (only on explicit user request).

## Reading MQTT topics

**Read a channel value:**
```bash
ssh root@<HOST> "mosquitto_sub -t '/devices/<device_id>/controls/<channel>' -C 1 -W 5"
```

**List devices/topics:**
```bash
ssh root@<HOST> "mosquitto_sub -t '/devices/+/meta/name' -C 100 -W 3"
```

**Write a value:**
```bash
ssh root@<HOST> "mosquitto_pub -t '/devices/<device_id>/controls/<channel>/on' -m '<value>'"
```

## Scenario "enable channel X on device Y"

1. Device list: `ssh root@<HOST> "mosquitto_sub -t '/devices/+/meta/name' -C 100 -W 3"` — find `device_id`.
2. **Channel list from the template** (including `enabled:false`): `ssh root@<HOST> 'jq ".device.channels[] | {name, enabled}" /usr/share/wb-mqtt-serial/templates/config-<device.id>.json'` — find out which channels even exist for this `device_type`.
3. **Backup:** `ssh root@<HOST> "cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)"`.
4. `config/Load({})` via RPC → save the result to `/tmp/wb-mqtt-serial.conf.new` on the controller.
5. Edit JSON — find the device in `ports[*].devices[*]`, add/update an entry `{"name": "<name>", "enabled": true}` in its `channels` (channel names come from the template, step 2).
6. Show the user a diff, warn about the `wb-mqtt-serial` restart (polling pauses ~5-10 sec).
7. `confed/Editor/Save` with `content:($c|fromjson)` (see example above — must be as an object, not a string).
8. After 10-20 sec: `ssh root@<HOST> "mosquitto_sub -t '/devices/<device_id>/controls/<channel>' -C 1 -W 20"`.

## Scenario "what's connected on the bus"

1. Ports: `ssh root@<HOST> "ls /dev/ttyRS485-* /dev/ttyMOD*"` or from `config/Load.config.ports`.
2. **`wb-device-manager/bus-scan/Start`** on each port with `scan_type:"extended"` (see above).
3. After each start — polling `/wb-device-manager/state` until `scanning:false`.
4. `state.devices` — array of `{title, sn, device_signature, port:{path}, cfg:{slave_id, baud_rate, parity, data_bits, stop_bits}, fw:{version}, online}`.
5. Compare with `config/Load.config.ports[*].devices` — what's already configured, what's new.

## Scenario "add devices found by the scanner to the config"

After `bus-scan` retained `/wb-device-manager/state` contains `devices[]` with `{device_signature, port.path, cfg.{slave_id,baud_rate,parity,data_bits,stop_bits}}`. Add — **one at a time, with confirmation at each step**.

Algorithm (no rigid script — follow step by step, at each show the user what you're going to do):

1. **Read the scan result**: `mosquitto_sub -t /wb-device-manager/state -C 1 -W 3` (examples above). Drop devices with `bootloader_mode:true`.

2. **Get mapping `signature → device_type`** once: call `wb-mqtt-serial/config/Load`, in the response `.result.types[].types[]` each template contains `hw[].signature`. The scan returns `device_signature` — find the matching `type` (= `device_type` for the config).

3. **Show the user the candidate table**: `port`, `slave_id`, `device_signature`, `device_type` (if found), `fw`, `sn`. In parallel — what's already in the config on those ports (call `confed/Editor/Load /etc/wb-mqtt-serial.conf` → `.result.content.ports[*].devices[*].slave_id`). Agree the list to add.

4. **For each confirmed device** — separate Load → mutate → Save:
   - `confed/Editor/Load /etc/wb-mqtt-serial.conf` — fresh snapshot (it could change between steps).
   - **Read the device template** (`/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json`) and collect default parameter values: `jq -c '[.device.parameters[] | select(.default != null) | {(.id): .default}] | add' <template>`. This is **mandatory** — the driver's schema requires all required parameters in the device record (typical case: WB-MAI6 `in1_type..in6_type`). Without defaults the config is rejected, polling on the entire bus won't start.
   - In `result.content.ports[]` find the port with the right `path`. If `slave_id` is already in its `devices` — skip and report. Otherwise append `{device_type, slave_id, enabled:true, ...defaults}` to its `devices`.
   - Show a mini-diff to the user (what will be added to this port).
   - `confed/Editor/Save` with `content` — **JSON object, not string** (payload format — see "Writing the config" block above). Confed validates and restarts `wb-mqtt-serial` itself, polling pauses ~5-10 sec.
   - After 10-20 sec verify publishing: `mosquitto_sub -t /devices/+/meta/name -C 100 -W 5 | grep <expected name>`.
   - If save failed validation (`Missing required property '...'`) — look at `journalctl -u wb-mqtt-serial -p err --since "1 min ago"` and add the missing parameters.

5. **Don't merge multiple devices into one Save** — if one of them fails schema validation (unknown `device_type` or collision), the rest also won't apply, and you'll have to debug what exactly broke.

### Pitfalls in auto-add

- **`device_signature` without a template** — skip and report to the user. Possibly a third-party device or a new WB module from a testing release whose template isn't in the installed firmware yet.
- **`slave_id` already configured** — collision. First reassign via `wb-mqtt-serial/device/Setup` (only on explicit user request), then add.
- **`baud_rate` of the device ≠ `port.baud_rate`** — adding will go through, but no polling. Solution via `device/Setup` or change port baud.
- **bootloader_mode: true** — device is in fw-update, too early to add; wait for completion and rescan.

## Direct file editing — backup mandatory

If without `confed/Editor/Save` (via `ssh ... cat >`) — first backup, then `systemctl restart wb-mqtt-serial`:

```bash
ssh root@<HOST> "cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)"
```

## Pitfalls

- **`confed/Editor/Save` with content as a string** — kills polling on the whole bus. `content` is always an object, not a serialized string. See the example with `jq -nc --rawfile c ... '... content:($c|fromjson) ...'` above.
- **`device/LoadConfig` ≠ channel list.** Returns `{fw, model, parameters}` — firmware parameters (debounce, modes, mappings). Channels — in the file `/usr/share/wb-mqtt-serial/templates/config-*.json`.
- **`templates/GetTemplate` RPC** — doesn't work on current firmwares (wb-2602, wb-2507) (timeout). Don't use.
- "Channel not supported" based on MQTT listing without reading the template — see above, `enabled:false` doesn't publish.
- `WebFetch` of the template from GitHub instead of reading the file on the controller — on the hardware it's more current.
- A custom template before checking the built-in.
- Direct `cat >` to `.conf` without validation — broken JSON kills bus polling.
- Editing packaged templates in `/usr/share/...` — overwritten by an update. Custom — only in `/etc/wb-mqtt-serial.conf.d/templates/`.
- `port/Scan` without timeout >= 30 sec — timeout, partial response.

## Documentation

- Wiki: <https://wirenboard.com/wiki/wb-mqtt-serial>
- Sources + templates: <https://github.com/wirenboard/wb-mqtt-serial>
- Module pages: `https://wirenboard.com/wiki/<Model>` (WB-MR6C, WB-MSW_v.4, etc.)
