---
name: wb-troubleshooting-serial
description: "Software diagnostics of the serial bus (RS-485, Modbus) on a Wiren Board controller. CRC errors, timeouts, device not responding, slow polling, debug logs, bus scan, device health check."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# troubleshooting-serial

Software diagnostics of the serial bus (RS-485, Modbus and other protocols) from the driver and MQTT level. Load this on: Modbus errors, CRC, timeouts, "device not responding", "data not updating", slow polling, read/write errors.

**IMPORTANT: Act without pauses. DON'T ask permission for each step — the user ALREADY asked for diagnostics, that's the confirmation. Execute ALL steps in sequence: logs -> debug -> scan -> health. DON'T stop with questions like "want to run debug?" or "if you want, I can..." — just do it. Report at the end.**

**HOST variable:** in all examples below `<HOST>` means `wirenboard-<SN>.local`, where `<SN>` is the serial number (e.g. `wirenboard-AABBCCDD.local`). Substitute the real address.

## MQTT RPC via Bash — base pattern

```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/<driver>/<service>/<method>/$CID/reply" -C 1 -W <timeout> & sleep 0.2; mosquitto_pub -t "/rpc/v1/<driver>/<service>/<method>/$CID" -m '"'"'{"id":1,"params":{...}}'"'"'; wait'
```

## Start with this

1. **Documentation about the device** — always show the source URL. Sequence:
   - `WebFetch("https://wirenboard.com/wiki/<DeviceModel>")` — device page, "Known issues" section
   - If nothing there — try a wiki web search right away (the domain has changed, try both): `WebSearch("site:wirenboard.com/wiki/ <DeviceModel> <error>")` or `WebSearch("site:wiki.wirenboard.com <DeviceModel> <error>")`
   - Look at the device changelog (`WebFetch` on the changelog page) — it often has ERRMODBUS codes and fixed bugs
   - **Always cite the URL** you got the info from

2. Is the driver alive:
   ```bash
   ssh root@<HOST> "systemctl is-active wb-mqtt-serial"
   ```

3. Logs — scope and type. First general count and last lines (don't narrow with regex — you'd miss noisy patterns like `[mqtt] connection lost`, `[serial client] Reading events failed`, `[backend] Unable to cleanup topic`, which don't have `device modbus:N`):
   ```bash
   ssh root@<HOST> "journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | wc -l; echo ---; journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | tail -30"
   ```
   Histogram by slave_id (in addition to the output above, not instead of):
   ```bash
   ssh root@<HOST> "journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | grep -oP 'device modbus:\\K\\d+' | sort | uniq -c | sort -rn"
   ```

4. **Debug — raw packets. RUN IMMEDIATELY, DON'T ASK.** This is a safe operation — the script enables and disables debug itself, restarts the driver itself. **This is an exception** to the general "ask before `systemctl restart wb-mqtt-serial`" rule (master skill): two restarts inside a debug session are part of the procedure itself and run without confirmation.

   Debug duration: divide 18000 by the number of errors per hour (from step 3). Result is in seconds. Minimum 30, maximum 300. If errors are 0 or just a few (<10/h) — set 120 sec: the issue is rare or transient, a long debug won't show anything anyway.

   Table:
   - <10 errors/hour → 120 sec (low rate, long collection isn't needed)
   - 10 errors/hour → 18000/10 = 1800 → cap 300 sec
   - 50 errors/hour → 360 → cap 300 sec
   - 100 errors/hour → 180 sec
   - 500 errors/hour → 36 sec
   - 1000+ errors/hour → 18 → floor 30 sec

   **Debug-collection script** — write it to the controller once, then run as a background job. Protected against incomplete exit: if something fails midway, `trap ... EXIT` guarantees `debug:false` is restored and the driver restarted. **Don't remove the `trap` — without it a hung restart leaves the controller in debug mode, filling the disk.**

   ```bash
   ssh root@<HOST> 'cat > /tmp/debug-serial.sh << '"'"'SCRIPT'"'"'
   #!/bin/bash
   set -e
   DURATION="${1:-120}"
   CONF=/etc/wb-mqtt-serial.conf
   LOG=/mnt/data/ai/wb-ai-skills/diag/debug-serial.log
   mkdir -p /mnt/data/ai/wb-ai-skills/diag

   # Captured-group regex — preserves original formatting (indents, spaces around :)
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
   # No -n: write the whole journal for the window (~3000 lines for 120s with debug=true; -n 500 truncates silently).
   journalctl -u wb-mqtt-serial --since "$START_TS" --no-pager > "$LOG"
   echo "[debug-serial] saved $(wc -l < "$LOG") lines to $LOG"
   SCRIPT
   chmod +x /tmp/debug-serial.sh'
   ```

   Start the background job (`<DURATION>` — calculated value, default 120):
   ```bash
   ssh root@<HOST> 'systemd-run --unit=wb-ai-job-$(cat /dev/urandom | tr -dc a-z0-9 | head -c8) --collect bash /tmp/debug-serial.sh <DURATION>'
   ```

   Wait for completion (`systemctl is-active wb-ai-job-...` → `inactive`, or `journalctl -u wb-ai-job-... -n 5`). Pick up the log:
   ```bash
   scp root@<HOST>:/mnt/data/ai/wb-ai-skills/diag/debug-serial.log /tmp/debug-serial.log
   ```
   (Local path — `/tmp/debug-serial.log` or another explicit path, not `./` — you don't have a stable cwd between calls.)

   **Immediately verify that debug is actually disabled:**
   ```bash
   ssh root@<HOST> 'grep -c "\"debug\"\s*:\s*false" /etc/wb-mqtt-serial.conf; systemctl is-active wb-mqtt-serial'
   ```
   Should be `1` and `active`. If `debug:true` remains — `trap` paths didn't fire; connect and do it by hand: `sed -i '"'"'s/\("debug"\s*:\s*\)true/\1false/'"'"' /etc/wb-mqtt-serial.conf && systemctl restart wb-mqtt-serial`.

   If the error didn't reproduce in 2 minutes — tell the user: the issue is rare, debug is off.

5. **Bus scan** — who's there, who isn't, duplicates. First find port parameters:
   ```bash
   ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/ports/Load/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/ports/Load/$CID" -m '"'"'{"id":1,"params":{}}'"'"'; wait'
   ```

   `ports/Load` returns only **active** ports (those the driver currently opens), not all physical `/dev/ttyRS485-*` and `/dev/ttyMOD*`. For a full list — `ls /dev/ttyRS485-* /dev/ttyMOD*`.

   Then run a scan via `wb-device-manager/bus-scan/Start` (async, progress/devices in retained `/wb-device-manager/state`):
   ```bash
   # Start (Start doesn't wait for completion)
   ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-device-manager/bus-scan/Start/$CID/reply" -C 1 -W 10 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-device-manager/bus-scan/Start/$CID" -m '"'"'{"id":1,"params":{"scan_type":"extended","preserve_old_results":false,"port":{"path":"/dev/ttyRS485-1","baud_rate":<actual>,"parity":"N","data_bits":8,"stop_bits":2}}}'"'"'; wait'

   # Polling until scanning:false
   ssh root@<HOST> 'for i in $(seq 1 60); do s=$(mosquitto_sub -t /wb-device-manager/state -C 1 -W 2); echo "$s" | jq -e ".scanning == false" >/dev/null && break; sleep 2; done; mosquitto_sub -t /wb-device-manager/state -C 1 -W 3 | jq ".devices"'
   ```

   `scan_type:"extended"` — Fast Modbus (WB+Onokom). `scan_type:"standard"` — regular Modbus, sees third-party devices. Third-party without full support — pinpointed via `modbus_client_rpc`. If a device is in `config/Load` but not in the scan result — **must** check it via `device/Probe` before concluding "it's dead" (a bug observed on WB-MAP6S via the old `port/Scan`).

6. **WB device health** — uptime + power (if the register maps to voltage):
   ```bash
   # Uptime (regs 104-105) — on all WB devices with WB-MS-protocol firmware:
   ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t 3 -r 104 -c 2 -b <baud> -s <stop> -p <parity> <path>"
   # Vsupply / Vmin (regs 121-122, mV) — on relays/dimmers/MCM, on MAI/MAP/MR3 may map differently:
   ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t 3 -r 121 -c 2 -b <baud> -s <stop> -p <parity> <path>"
   ```
   **Registers 121-122 are not universal** — on WB-MAI6/WB-MAP6S and some MR3 they may return input/measurement, not Vsupply. If the value is clearly implausible for voltage (5V, fractions of a volt at 24V supply) — for this model the register is different; see the device wiki page.

7. **Save the report on the controller:**
   ```bash
   echo '<report text>' | ssh root@<HOST> 'cat > /mnt/data/ai/wb-ai-skills/diag/serial-diag.txt'
   ```

## Device firmware version

If the firmware version of a specific WB device is needed — **don't ask the user**, do this:

1. Load the driver config:
   ```bash
   ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/config/Load/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/config/Load/$CID" -m '"'"'{"id":1,"params":{}}'"'"'; wait'
   ```
2. Find the device by slave_id, remember its `device_type` (e.g. `WB-MDM3`).
3. Read the template **from the file** on the controller (`templates/GetTemplate` RPC doesn't work on current firmwares — gives a timeout):
   ```bash
   ssh root@<HOST> 'for f in /usr/share/wb-mqtt-serial/templates/*.json; do dt=$(jq -r ".device_type // \"\"" "$f" 2>/dev/null); [ "$dt" = "<device_type>" ] && jq ".device.channels[] | {name, enabled}" "$f" && break; done'
   ```
4. In the output find a channel with a name resembling firmware version: `FW Version`, `Firmware Version`, `SW Version`, `Serial`, etc.
5. In the driver config find this channel for the right device and enable it: `"enabled": true`. If the channel isn't in `channels` — add it.
6. Save the config via `confed/Editor/Save` (see `wb-mqtt-serial` skill, the section about `content:($c|fromjson)` — content must be a **JSON object**, not a serialized string).
7. After 10-20 seconds read the value from MQTT:
   ```bash
   ssh root@<HOST> "mosquitto_sub -t '/devices/<device_id>/controls/<channel_name>' -C 1 -W 20"
   ```

Example: on `wb-mdm3_57` the channel is called `FW Version`. On another device it may be different — always look at the template.

## Patterns: saw -> do

| Saw | Do |
|---|---|
| `invalid crc` in logs | Debug -> look at raw packet. Bad CRC = noise/contact. Foreign slave_id = duplicate |
| `request timed out` | `device/Probe` -> alive? If silent — physical, power, slave_id |
| `invalid data size` | Scan -> look for slave_id duplicates. Debug -> extra bytes = collision |
| `rate limit exceeded` | Spread devices across ports, increase baud, disable extra channels |
| Device in scan but not in config | May interfere! Add or physically disconnect |
| Device in config but not in scan | Off, broken, or third-party (scan doesn't see) |
| CRC on all devices | Noise, 120 Ω terminator, grounding. Experiment: lower the speed |
| CRC on one | Connect with a short wire. If it works — line problem |
| Other stop bits help | Mismatch between port and device parameters |
| Min voltage < 20V (reg 122) | Power dips -> PSU, wire gauge |
| Small uptime (regs 104-105) | Device rebooted -> power |
| Exception code in debug | 1=illegal FC, 2=illegal addr, 3=illegal value, 4=device failure |
| Non-Modbus protocol in config | modbus_client_rpc and scan won't help, only logs and debug |

## Tools

**modbus_client_rpc** (preferred) — through the driver queue, safe:
```bash
ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t <FC> -r <reg> -c <count> -b <baud> -s <stop> -p <parity> <port>"
```
FC: 1=coils, 2=discrete, 3=holding, 4=input, 5=write coil, 6=write reg, 15=write coils, 16=write regs.

**device/Probe** — quick "alive?" check:
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/device/Probe/$CID/reply" -C 1 -W 10 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/device/Probe/$CID" -m '"'"'{"id":1,"params":{"path":"/dev/ttyRS485-1","baud_rate":9600,"data_bits":8,"parity":"N","stop_bits":2,"slave_id":<ID>,"total_timeout":10000}}'"'"'; wait'
```

**ports/Load** — port parameters:
```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/wb-mqtt-serial/ports/Load/$CID/reply" -C 1 -W 5 & sleep 0.2; mosquitto_pub -t "/rpc/v1/wb-mqtt-serial/ports/Load/$CID" -m '"'"'{"id":1,"params":{}}'"'"'; wait'
```

**wb-modbus-scanner** — Fast Modbus utility (WB, Onokom). `apt install wb-modbus-ext-scanner`. Conflicts with the driver — requires stopping wb-mqtt-serial (agree with the user!).
```bash
ssh root@<HOST> "wb-modbus-scanner -d <port> -b <baud>"        # scan
ssh root@<HOST> "wb-modbus-scanner -d <port> -s <sn> -i <id>"  # change slave_id
```

**modbus_client** — direct access. Conflicts with the driver — requires stopping wb-mqtt-serial (agree with the user!).

## Useful WB device registers

| Register | What | Format |
|---|---|---|
| 104-105 | Uptime | u32, seconds (universal across all WB devices) |
| 110 | Baud rate | u16, abbreviated: 96=9600, 1152=115200 |
| 121 | Supply voltage | u16, mV — **only relays/dimmers/MCM** (on MAI/MAP/MR3 the register maps to other measurements) |
| 122 | Min voltage | u16, mV (since boot) — same place as 121 |
| 128 | Slave ID | u16 |
| 200-205 | Model | string |
| 270-271 | Serial number | u32 |

Broadcast write (slave_id 0) — change baud/address for all WB devices on the bus at once.

baud_rate `1152` = `115200` — abbreviated form, NOT an error.

## Experiments (backup + agree with the user)

Before experiments:
```bash
ssh root@<HOST> "cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)"
```

- **Stop bits**: try 1 and 2 via `modbus_client_rpc -s 1` / `-s 2`
- **Speed**: broadcast `modbus_client_rpc -a 0 -t 6 -r 110 ... 96` -> change port via confed. Errors gone = cable/termination
- **Isolation**: `config/Load` -> `"enabled": false` -> `confed/Editor/Save`. Errors gone on the rest = this device interferes
- **Timeouts**: `response_timeout_ms`, `guard_interval_us` in port config

**Roll everything back after experiments.**

## Pitfalls

- `modbus_client`/`wb-modbus-scanner` without stopping the driver -> false errors
- Forgotten debug -> disk fills up
- port/Scan -> only WB and Onokom
- Wrong baud -> COMPLETELY silent. Wrong stop bits -> floating errors
- RS-485 in star topology works on short distances; for issues — recommend daisy chain

## Documentation

- <https://wiki.wirenboard.com/wiki/RS-485>
- <https://wiki.wirenboard.com/wiki/Modbus>
- <https://wiki.wirenboard.com/wiki/Common_Modbus_Registers>
- <https://wiki.wirenboard.com/wiki/How_to_diagnose>
- <https://github.com/wirenboard/wb-modbus-ext-scanner/blob/main/docs/protocol.ru.md>
