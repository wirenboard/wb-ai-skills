---
name: wb-serial
description: "Serial bus (RS-485/Modbus) on WB — custom templates, adding devices via confed, and diagnostics: CRC errors, timeouts, device not responding, slow polling, bus scan, health check."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# wb-serial

## CRITICAL RULES

> **NEVER call `wb-cli` without `--json` from an agent.**
> Human-mode output is unparseable; always use:
> `wb-cli --json <command>`
> This applies to every call including help: `wb-cli --json <group> --help`.

**`<HOST>` variable:** in all examples below `<HOST>` means `wirenboard-<SN>.local`, where `<SN>` is the serial number (e.g. `wirenboard-AABBCCDD.local`). Substitute the real address.

## When to load this skill

- **Templates**: "no template for the device", "add a third-party Modbus device", "create a template", "how to add custom registers", "template for an energy meter", "Modbus thermometer".
- **Diagnostics**: Modbus errors, CRC, timeouts, "device not responding", "data not updating", slow polling, read/write errors.

**IMPORTANT for diagnostics: Act without pauses. DON'T ask permission for each step — the user ALREADY asked for diagnostics. Execute ALL steps in sequence: logs → debug → scan → health. DON'T stop with questions like "want to run debug?" — just do it. Report at the end.**

## MQTT RPC via Bash — base pattern

```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/<driver>/<service>/<method>/$CID/reply" -C 1 -W <timeout> & sleep 0.2; mosquitto_pub -t "/rpc/v1/<driver>/<service>/<method>/$CID" -m '"'"'{"id":1,"params":{...}}'"'"'; wait'
```

## wb-cli shortcuts

```bash
ssh root@<HOST> wb-cli --json serial-debug --port /dev/ttyRS485-1 --seconds 60
ssh root@<HOST> wb-cli --json serial wb-scan --port /dev/ttyRS485-1
ssh root@<HOST> wb-cli --json serial devices
ssh root@<HOST> wb-cli --json serial device-params 52
ssh root@<HOST> wb-cli --json dev wb-mr6c_52
```

---

# Part 1 — Templates and device configuration

## Where templates live

| Directory | What | Editable? |
|---------|-----|----------------|
| `/usr/share/wb-mqtt-serial/templates/config-<mqtt-id>.json` | Packaged WB and Onokom templates | NO — overwritten by `apt upgrade` |
| `/etc/wb-mqtt-serial.conf.d/templates/<any-name>.json` | Custom templates | Yes, survive upgrade |
| `/etc/wb-mqtt-serial.conf.d/confs/*.conf` | Custom parts of the main config | Less commonly used |

`wb-mqtt-serial` scans both directories at start. A custom template with the same `device_type` as a packaged one **overrides** the packaged one.

## Minimal template structure

```json
{
  "title": "ACME EM-100 (1-phase energy meter)",
  "device_type": "ACME-EM100",
  "group": "g_energy_meters",
  "device": {
    "name": "ACME EM-100",
    "id": "acme-em100",
    "channels": [
      {
        "name": "Voltage",
        "reg_type": "input",
        "address": 0,
        "format": "u16",
        "scale": 0.1,
        "type": "voltage",
        "units": "V"
      }
    ]
  }
}
```

`device_type` — what goes into `/etc/wb-mqtt-serial.conf` (`ports[*].devices[*].device_type`).
`device.id` — MQTT topic prefix (`wb-mqtt-serial` will create `/devices/<id>_<slave_id>/...`).

## Channel fields (full set)

| Field | Purpose |
|------|-----------|
| `name` | Control name in MQTT (spaces OK) |
| `reg_type` | `coil` (FC1, RW), `discrete` (FC2, RO), `holding` (FC3, RW), `input` (FC4, RO) |
| `address` | Register address (decimal) |
| `format` | `u8`, `s8`, `u16`, `s16`, `u32`, `s32`, `u64`, `s64`, `bcd16`, `bcd32`, `bcd64`, `float`, `double`, `string`, `varstring` |
| `scale` | Multiplier `value = raw * scale` |
| `offset` | Added after scale |
| `round_to` | Round to N digits |
| `type` | MQTT control type: `switch`, `value`, `voltage`, `current`, `power`, `energy_power`, `temperature`, `pressure`, `range`, `text`, `pushbutton` |
| `units` | Units (V, A, °C, mWh) |
| `error_value` | If raw == this, control publishes error |
| `unsupported_value` | If raw == this, control isn't published |
| `read_rate_limit_ms` | Don't poll more often than once every N ms |
| `enabled` | `false` — channel disabled by default (enabled via UI) |
| `readonly` | `true` — only read even for `holding`/`coil` |
| `sporadic` | `true` — request only when driver already polls |
| `condition` | Expression on `parameters` fields — channel only visible if true |
| `group` | Group ID for UI |
| `word_order` | `big_endian` (default) or `little_endian` for multi-register values |

### Endianness

Modbus is byte big-endian, but for u32/s32/float the **word** order (16-bit registers) is often little-endian for some manufacturers. Symptom: value "jumps strangely" — try `"word_order": "little_endian"`.

### `string` / `varstring`

```json
{
  "name": "FW Version",
  "reg_type": "input",
  "address": 250,
  "format": "string",
  "size": 8,
  "type": "text"
}
```

## `parameters` — firmware settings

```json
"parameters": [
  {
    "id": "in0_mode",
    "title": "Input 0 mode",
    "address": 1100,
    "reg_type": "holding",
    "format": "u16",
    "default": 0,
    "enum": [0, 1, 2, 3],
    "enum_titles": [
      {"en": "Switch"},
      {"en": "Push button"},
      {"en": "RS-trigger"},
      {"en": "Counter"}
    ],
    "group": "g_in0_setup"
  }
]
```

`condition` in a channel can look at a parameter `id`: `"condition": "in0_mode==3"`.

## `groups` — UI grouping

```json
"groups": [
  {"id": "g_inputs", "title": "Inputs"},
  {"id": "g_in0_channels", "title": "Input 0", "group": "g_inputs"}
]
```

## `translations` — i18n

```json
"translations": {
  "ru": {
    "Voltage": "Напряжение"
  }
}
```

## Template creation workflow

### 1. Device documentation

`WebFetch` the manufacturer's manual — register table (addresses, types, scale). Without it, don't make a template; guessing = endless debugging.

### 2. List existing templates and pick a starter

```bash
ssh root@<HOST> wb-cli --json serial templates                  # list all template filenames
ssh root@<HOST> wb-cli --json serial template wb-mr6c           # show full JSON of a template
```

Copy a similar one as a starter:

```bash
ssh root@<HOST> 'cp /usr/share/wb-mqtt-serial/templates/config-wb-mr6c.json /etc/wb-mqtt-serial.conf.d/templates/acme-em100.json'
```

### 3. Test on one channel

First a template with **one** channel. Add the device to `/etc/wb-mqtt-serial.conf` via confed (see below), verify the channel publishes and the value is plausible:

```bash
ssh root@<HOST> wb-cli --json dev <device.id>_<slave_id>
# or read a single value:
ssh root@<HOST> wb-cli --json mqtt read '/devices/<device.id>_<slave_id>/controls/<channel>'
```

If the value doesn't match expectations — tweak `format`, `scale`, `word_order`. Direct ground-truth measurement:

```bash
ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t 4 -r <addr> -c <count> -b <baud> -s 2 -p N <port>"
```

(`-t 4` = input registers FC4. FC table in Part 2 → Tools.)

### 4. Expand to all channels

Add in batches of 5-10, after each — verify via MQTT.

### 5. Parameters and groups

When base telemetry works — add `parameters` for settings, `groups` for UI.

### 6. Template in Git/backup

A custom template won't survive FIT. Goes into backup automatically via `wb-controller-backup` skill (picks up `/etc/wb-mqtt-serial.conf.d/`). For a full list of what survives FIT, see `wb-controller-backup` skill.

## Adding a device to wb-mqtt-serial

> **CRITICAL: NEVER edit `/etc/wb-mqtt-serial.conf` manually or via raw confed API.**
> wb-mqtt-serial templates have required parameters that must be present in the config.
> Missing them causes config validation failure → `ports/Load` returns `[]` →
> **all bus scans stop working** until the config is fixed.
> Always use `wb-cli serial add-devices` — it fills required params from template defaults automatically.

### Standard workflow: scan → add

```bash
# Extended scan (WB Fast Modbus devices — default, fast)
ssh root@<HOST> wb-cli --json serial wb-scan

# Slow scan (third-party devices without Fast Modbus support)
ssh root@<HOST> wb-cli --json serial wb-scan --slow --timeout 300

# Add all found devices on a port (reads last scan result, no re-scan)
ssh root@<HOST> wb-cli --json serial add-devices --port /dev/ttyRS485-1
```

`add-devices` reads the retained wb-device-manager state — so you can run any scan type
(extended or slow) and then add without re-scanning. Devices already in config are skipped.

**Automatic fixups** applied before adding (scan mode only):

| Issue | Action |
|---|---|
| Device baud ≠ port baud | Writes reg 110 at device's current speed → device switches to port's baud |
| Two scan devices same slave_id | Reassigns duplicate via Fast Modbus by SN (WB/Onokom) or reg 128; without SN — warns and skips |
| Scan device slave_id conflicts with existing config (different device_type) | Reassigns via Fast Modbus by SN or reg 128 |

### Add a single device by model (no scan needed)

```bash
ssh root@<HOST> wb-cli --json serial add-devices \
  --port /dev/ttyRS485-1 --device-type WB-MAI6 --slave-id 19
```

Looks up the template, fills required parameters from defaults, appends to config.

### `add-devices` result

```json
{
  "port": "/dev/ttyRS485-1",
  "added": [
    {"slave_id": 7,  "device_type": "WB-MR6C"},
    {"slave_id": 1,  "device_type": "WB-MAO4-20mA", "slave_id_changed": "18 → 1", "baud_changed": "115200 → 9600"}
  ],
  "skipped": [],
  "count": 2,
  "warnings": []
}
```

`warnings` is present when:
- Template not found — required parameters not filled; validate config manually.
- Address collision without SN — cannot reassign safely; device skipped.
- Baud change failed — device unreachable; check connectivity and skip.

After adding, `wb-mqtt-serial` reloads automatically. Verify: `wb-cli --json dev <device_id>`.

## Reading and writing device parameters

`device-params` reads the `parameters` section (firmware settings) from the device hardware via the driver's `device/LoadConfig` RPC. The device must already be in the config.

```bash
# Read parameters by slave_id or by device id
ssh root@<HOST> wb-cli --json serial device-params 52
ssh root@<HOST> wb-cli --json serial device-params wb-mr6c-52

# Bypass driver cache (force re-read from hardware)
ssh root@<HOST> wb-cli --json serial device-params 52 --force
```

Returns `{"slave_id": 52, "device_type": "WB-MR6C", "model": "...", "fw": {"version": "..."}, "parameters": {"in0_mode": 0, ...}}`.

`device-set` writes one or more parameters to the device via `device/Set` RPC:

```bash
ssh root@<HOST> wb-cli --json serial device-set 52 --set in0_mode=1 --set in1_mode=3
```

`KEY=VALUE` — values are coerced: integers first, then floats, then strings. Returns the parameters that were written.

**Note:** Both commands look up the device by `slave_id` or `id` field from `/etc/wb-mqtt-serial.conf`. The driver uses the template's `parameters` section to know which registers to read/write — so the device must be in config with the correct `device_type`.

## Listing devices and ports

```bash
# All devices from /etc/wb-mqtt-serial.conf (with protocol column)
ssh root@<HOST> wb-cli --json serial devices

# Filter to one port
ssh root@<HOST> wb-cli --json serial devices --port /dev/ttyRS485-1

# Active ports (driver-side, only what's currently open)
ssh root@<HOST> wb-cli --json serial ports
```

## Loading / testing without restart

```bash
ssh root@<HOST> 'systemctl restart wb-mqtt-serial'
```

Template parsing logs:

```bash
ssh root@<HOST> 'journalctl -u wb-mqtt-serial -n 50 --no-pager | grep -iE "(template|<device.id>)"'
```

---

# Part 2 — Diagnostics

## Start with this

1. **Documentation about the device** — always show the source URL. Sequence:
   - `WebFetch("https://wirenboard.com/wiki/<DeviceModel>")` — device page, "Known issues" section
   - If nothing there — `WebSearch("site:wirenboard.com/wiki/ <DeviceModel> <error>")`
   - Look at the device changelog — it often has ERRMODBUS codes and fixed bugs
   - **Always cite the URL** you got the info from

2. Is the driver alive:
   ```bash
   ssh root@<HOST> "systemctl is-active wb-mqtt-serial"
   ```

3. Logs — scope and type. First general count and last lines (don't narrow with regex — you'd miss noisy patterns):
   ```bash
   ssh root@<HOST> "journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | wc -l; echo ---; journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | tail -30"
   ```
   Histogram by slave_id:
   ```bash
   ssh root@<HOST> "journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | grep -oP 'device modbus:\\K\\d+' | sort | uniq -c | sort -rn"
   ```

4. **Debug — raw packets. RUN IMMEDIATELY, DON'T ASK.** Safe operation — the script enables/disables debug itself, restarts the driver itself. **Exception** to the general "ask before `systemctl restart`" rule: two restarts inside a debug session are part of the procedure.

   Debug duration: divide 18000 by the number of errors per hour (from step 3). Minimum 30, maximum 300. If <10 errors/h — set 120 sec.

   | Errors/hour | Duration |
   |---|---|
   | <10 | 120 sec |
   | 10-59 | 300 sec (cap) |
   | 60-99 | 300 sec (cap) |
   | 100 | 180 sec |
   | 500 | 36 sec → floor 30 sec |
   | 1000+ | 18 sec → floor 30 sec |

   **Debug-collection script** — write it to the controller, then run as a background job. `trap` guarantees `debug:false` is restored on exit. **Don't remove the `trap` — without it a hung restart leaves the controller in debug mode, filling the disk.**

   ```bash
   ssh root@<HOST> 'cat > /tmp/debug-serial.sh << '"'"'SCRIPT'"'"'
   #!/bin/bash
   set -e
   DURATION="${1:-120}"
   CONF=/etc/wb-mqtt-serial.conf
   LOG=/mnt/data/ai/wb-ai-skills/diag/debug-serial.log
   mkdir -p /mnt/data/ai/wb-ai-skills/diag

   restore_debug_off() {
     sed -i '"'"'s/\("debug"\s*:\s*\)true/\1false/'"'"' "$CONF"
     systemctl restart wb-mqtt-serial >/dev/null 2>&1 || true
     echo "[debug-serial] restored debug:false"
   }
   trap restore_debug_off EXIT INT TERM

   sed -i '"'"'s/\("debug"\s*:\s*\)false/\1true/'"'"' "$CONF"
   systemctl restart wb-mqtt-serial
   sleep 1
   START_TS=$(date -u +%Y-%m-%dT%H:%M:%S)
   echo "[debug-serial] collecting ${DURATION}s from $START_TS"
   sleep "$DURATION"
   journalctl -u wb-mqtt-serial --since "$START_TS" --no-pager > "$LOG"
   echo "[debug-serial] saved $(wc -l < "$LOG") lines to $LOG"
   SCRIPT
   chmod +x /tmp/debug-serial.sh'
   ```

   Start the background job:
   ```bash
   ssh root@<HOST> wb-cli --json job run serial-debug "bash /tmp/debug-serial.sh <DURATION>"
   ```

   Wait for completion:
   ```bash
   ssh root@<HOST> wb-cli --json job wait serial-debug
   ```
   Pick up the log:
   ```bash
   scp root@<HOST>:/mnt/data/ai/wb-ai-skills/diag/debug-serial.log /tmp/debug-serial.log
   ```

   **Verify debug is disabled:**
   ```bash
   ssh root@<HOST> 'grep -c "\"debug\"\s*:\s*false" /etc/wb-mqtt-serial.conf; systemctl is-active wb-mqtt-serial'
   ```
   Should be `1` and `active`.

5. **Bus scan** — who's there, who isn't, duplicates. First find port parameters:

   Use the MQTT RPC base pattern from the top of this skill. Driver: `wb-mqtt-serial`, service: `ports`, method: `Load`, params: `{}`, timeout: 5.

   `ports/Load` returns only **active** ports (those the driver currently opens). For a full list — `ls /dev/ttyRS485-* /dev/ttyMOD*`.

   Then run a scan via `wb-device-manager/bus-scan/Start` (async):

   Use the MQTT RPC base pattern from the top of this skill. Driver: `wb-device-manager`, service: `bus-scan`, method: `Start`, params: `{"scan_type":"extended","preserve_old_results":false,"port":{"path":"/dev/ttyRS485-1","baud_rate":<actual>,"parity":"N","data_bits":8,"stop_bits":2}}`, timeout: 10.

   Poll for completion:
   ```bash
   ssh root@<HOST> 'for i in $(seq 1 60); do s=$(wb-cli --json mqtt read /wb-device-manager/state 2>/dev/null); echo "$s" | jq -e ".data.payload | fromjson | .scanning == false" >/dev/null 2>&1 && break; sleep 2; done; wb-cli --json mqtt read /wb-device-manager/state | jq -r ".data.payload | fromjson | .devices"'
   ```

   `scan_type:"extended"` — Fast Modbus (WB+Onokom). `scan_type:"standard"` — regular Modbus, sees third-party devices.

6. **WB device health** — uptime + power:
   ```bash
   # Uptime (regs 104-105) — on all WB devices with WB-MS-protocol firmware:
   ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t 3 -r 104 -c 2 -b <baud> -s <stop> -p <parity> <path>"
   # Vsupply / Vmin (regs 121-122, mV) — on relays/dimmers/MCM:
   ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t 3 -r 121 -c 2 -b <baud> -s <stop> -p <parity> <path>"
   ```
   **Registers 121-122 are not universal** — on WB-MAI6/WB-MAP6S and some MR3 they may return other values. If implausible — see the device wiki page.

7. **Save the report on the controller:**
   ```bash
   echo '<report text>' | ssh root@<HOST> 'cat > /mnt/data/ai/wb-ai-skills/diag/serial-diag.txt'
   ```

## Device firmware version

If the firmware version of a specific WB device is needed — **don't ask the user**:

1. Use the MQTT RPC base pattern. Driver: `wb-mqtt-serial`, service: `config`, method: `Load`, params: `{}`, timeout: 5.
2. Find the device by slave_id, remember its `device_type`.
3. Read the template from file on the controller:
   ```bash
   ssh root@<HOST> 'for f in /usr/share/wb-mqtt-serial/templates/*.json; do dt=$(jq -r ".device_type // \"\"" "$f" 2>/dev/null); [ "$dt" = "<device_type>" ] && jq ".device.channels[] | {name, enabled}" "$f" && break; done'
   ```
4. Find a channel named `FW Version`, `Firmware Version`, `SW Version`, `Serial`, etc.
5. Enable it in the driver config (`"enabled": true`), save via confed.
6. After 10-20 seconds read from MQTT:
   ```bash
   ssh root@<HOST> wb-cli --json mqtt read '/devices/<device_id>/controls/<channel_name>'
   ```

## Patterns: saw → do

| Saw | Do |
|---|---|
| `invalid crc` in logs | Debug → look at raw packet. Bad CRC = noise/contact. Foreign slave_id = duplicate |
| `request timed out` | `device/Probe` → alive? If silent — physical, power, slave_id |
| `invalid data size` | Scan → look for slave_id duplicates. Debug → extra bytes = collision |
| `rate limit exceeded` | Spread devices across ports, increase baud, disable extra channels |
| Device in scan but not in config | May interfere! Add or physically disconnect |
| Device in config but not in scan | Off, broken, or third-party (scan doesn't see) |
| CRC on all devices | Noise, 120 Ω terminator, grounding. Experiment: lower the speed |
| CRC on one device | Connect with a short wire. If it works — line problem |
| Other stop bits help | Mismatch between port and device parameters |
| Min voltage < 20V (reg 122) | Power dips → PSU, wire gauge |
| Small uptime (regs 104-105) | Device rebooted → power |
| Exception code in debug | 1=illegal FC, 2=illegal addr, 3=illegal value, 4=device failure |
| Non-Modbus protocol in config | modbus_client_rpc and scan won't help, only logs and debug |

## Tools

**modbus_client_rpc** (preferred) — through the driver queue, safe:
```bash
ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t <FC> -r <reg> -c <count> -b <baud> -s <stop> -p <parity> <port>"
```
FC: 1=coils, 2=discrete, 3=holding, 4=input, 5=write coil, 6=write reg, 15=write coils, 16=write regs.

**device/Probe** — quick "alive?" check:

Use the MQTT RPC base pattern. Driver: `wb-mqtt-serial`, service: `device`, method: `Probe`, params: `{"path":"/dev/ttyRS485-1","baud_rate":9600,"data_bits":8,"parity":"N","stop_bits":2,"slave_id":<ID>,"total_timeout":10000}`, timeout: 10.

**wb-modbus-scanner** — Fast Modbus utility (WB, Onokom). `apt install wb-modbus-ext-scanner`. Conflicts with the driver — requires stopping wb-mqtt-serial (agree with the user!).
```bash
ssh root@<HOST> "wb-modbus-scanner -d <port> -b <baud>"        # scan
ssh root@<HOST> "wb-modbus-scanner -d <port> -s <sn> -i <id>"  # change slave_id
```

**modbus_client** — direct access. Conflicts with the driver — requires stopping wb-mqtt-serial (agree with the user!).

## Useful WB device registers

All WB devices expose a standard set of Modbus holding registers documented at <https://wiki.wirenboard.com/wiki/Common_Modbus_Registers>. Device-specific registers are in the device's own wiki page. Always check both.

| Register | What | Format |
|---|---|---|
| 104-105 | Uptime | u32, seconds (universal across all WB devices) |
| 110 | Baud rate | u16, abbreviated: 96=9600, 1152=115200 |
| 121 | Supply voltage | u16, mV — **only relays/dimmers/MCM** |
| 122 | Min voltage | u16, mV (since boot) — same place as 121 |
| 128 | Slave ID | u16 |
| 200-205 | Model | string |
| 270-271 | Serial number | u32 |

Broadcast write (slave_id 0) — change baud/address for all WB devices on the bus at once.

baud_rate `1152` = `115200` — abbreviated form, NOT an error.

## Fast Modbus (WB extension protocol)

WB devices support a Wirenboard extension to Modbus RTU that enables:
- **Bus scan by serial number** — find all WB/Onokom devices even with duplicate slave_ids
- **Targeted commands by SN** — send any Modbus command to a specific device using its serial number instead of slave_id (critical when two devices share the same address)
- **Events** — devices proactively push register changes (inputs, counters, alarms) without polling; useful for low-latency diagnostics

All Fast Modbus frames use broadcast address `0xFD` and command byte `0x46`.

### Key frame types

| Subcommand | Direction | Purpose |
|---|---|---|
| `0x01` | → | Scan start — all devices reset scan status |
| `0x02` | → | Scan next — request next unscanned device |
| `0x03` | ← | Scan response — device replies with SN + slave_id |
| `0x04` | ← | Scan end — no more unscanned devices |
| `0x08` | → | Send standard Modbus PDU addressed by SN |
| `0x09` | ← | Response to `0x08` |
| `0x10` | → | Poll events |
| `0x11` | ← | Event packet from device |
| `0x12` | ← | No events |

### Change slave_id by serial number

When two devices share the same slave_id (factory default collision), use Fast Modbus to target by SN:

```
→ FD 46 08 [SN 4 bytes BE] 06 00 80 00 [new_id u16 BE] [CRC16 LE]
← FD 46 09 [SN 4 bytes BE] 06 00 80 00 [new_id u16 BE] [CRC16 LE]
```

- `0x08` = standard PDU by SN; `06` inside = FC6 write single holding register; `0x0080` = reg 128 (slave_id)
- SN comes from the extended scan result (`sn` field in wb-cli scan output)

### Change baud rate by SN

```
→ FD 46 08 [SN 4 bytes BE] 06 00 6E [baud_abbrev u16 BE] [CRC16 LE]
```

- Register `0x006E` = 110 (baud); value abbreviated: 96=9600, 1152=115200
- Send at the **device's current baud rate**; device switches immediately after ACK

### Sending Fast Modbus via port/Load RPC (no driver stop needed)

`wb-mqtt-serial` exposes `port/Load` RPC which accepts `"protocol": "raw"` — sends arbitrary bytes through the driver's own serial queue and returns the response. **No need to stop wb-mqtt-serial.**

Use the MQTT RPC base pattern with:
- driver: `wb-mqtt-serial`, service: `port`, method: `Load`
- timeout: use `total_timeout` value in seconds + 2

```json
{
  "path": "/dev/ttyRS485-1",
  "baud_rate": 9600,
  "parity": "N",
  "data_bits": 8,
  "stop_bits": 2,
  "protocol": "raw",
  "format": "HEX",
  "msg": "FD460800020B860600800001<CRC-LE>",
  "response_size": 14,
  "response_timeout": 100,
  "frame_timeout": 20,
  "total_timeout": 5000
}
```

- `msg`: hex string of the raw bytes to send (no spaces). CRC is part of the message — build it manually.
- `response_size`: expected response length in bytes
- `response_timeout`: ms to wait for first byte
- `frame_timeout`: ms inter-byte gap that ends the frame
- Response: `{"response": "<hex bytes>"}` in `HEX` format

**Modbus CRC-16** (LE): polynomial `0xA001`, init `0xFFFF`, append low byte then high byte.

This is how `wb-cli serial add-devices` and `modbus_client_rpc` work internally — they go through the same queue and don't conflict with the driver's ongoing polling.

### When to use Fast Modbus in diagnostics

- **Duplicate slave_id** on scan — `wb-cli serial add-devices` resolves automatically via SN. If you need to do it manually: `wb-cli serial send --port ... --msg 'FD 46 08 <SN 4B> 06 00 80 00 <new_id>' --add-modbus-crc --response-size 14`
- **Device in scan but won't respond to modbus_client_rpc** — address conflict; use `0x08` by SN to read model/firmware first
- **Event-based debugging** — instead of polling, subscribe to device events for input changes, counter ticks, resets. Useful to catch rare events without log noise.
- **wb-modbus-scanner** (`apt install wb-modbus-ext-scanner`) — reference CLI tool for Fast Modbus. Not installed by default; conflicts with driver while running.

### Reading device parameters during diagnostics

When you suspect misconfigured firmware settings, read them directly from hardware:

```bash
ssh root@<HOST> wb-cli --json serial device-params <slave_id>
```

Returns the current `parameters` values (e.g. input modes, relay behaviours, thresholds). Compare with expected values from the template or user settings. To apply a fix in-place without editing the config file:

```bash
ssh root@<HOST> wb-cli --json serial device-set <slave_id> --set <param>=<value>
```

Protocol spec: <https://github.com/wirenboard/wb-modbus-ext-scanner/blob/main/docs/protocol.en.md>

## Experiments (backup + agree with the user)

Before experiments:
```bash
ssh root@<HOST> "cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)"
```

- **Stop bits**: try 1 and 2 via `modbus_client_rpc -s 1` / `-s 2`
- **Speed**: broadcast `modbus_client_rpc -a 0 -t 6 -r 110 ... 96` → change port via confed. Errors gone = cable/termination
- **Isolation**: `config/Load` → `"enabled": false` → save. Errors gone on the rest = this device interferes
- **Timeouts**: `response_timeout_ms`, `guard_interval_us` in port config

**Roll everything back after experiments.**

## Pitfalls

- Template in `/usr/share/wb-mqtt-serial/templates/` — overwritten on upgrade. Only `/etc/wb-mqtt-serial.conf.d/templates/`.
- Endianness — most common error for u32/s32/float. If the value jumps by a 65535 factor — `word_order: little_endian`.
- Scale in the wrong direction — test on one channel.
- Duplicate `device_type` — silently overrides packaged template. Use a prefix like `ACME-`.
- Cyrillic in `device.id` — forbidden (goes into topic name). Only `[a-z0-9-]`.
- Address 0-based vs 1-based — check the device spec.
- No `error_value` — if device returns FFFF for "no data", MQTT will show 65535 as valid.
- `modbus_client`/`wb-modbus-scanner` without stopping the driver → false errors.
- Forgotten debug → disk fills up.
- Wrong baud → COMPLETELY silent. Wrong stop bits → floating errors.
- RS-485 in star topology works on short distances; for issues — recommend daisy chain.

## Documentation

- Template format: <https://github.com/wirenboard/wb-mqtt-serial/blob/master/docs/template.md>
- RS-485: <https://wiki.wirenboard.com/wiki/RS-485>
- Modbus: <https://wiki.wirenboard.com/wiki/Modbus>
- Common registers: <https://wiki.wirenboard.com/wiki/Common_Modbus_Registers>
- Diagnostics guide: <https://wiki.wirenboard.com/wiki/How_to_diagnose>
- Modbus FC spec: <https://modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf>
- Examples: `/usr/share/wb-mqtt-serial/templates/` on the controller (250+ templates).
