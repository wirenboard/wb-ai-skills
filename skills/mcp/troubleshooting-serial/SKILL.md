---
name: troubleshooting-serial
description: "Software diagnostics of the serial bus (RS-485, Modbus) on a Wiren Board controller via MCP. CRC errors, timeouts, device not responding, slow polling, debug logs, bus scanning, device health checks."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# troubleshooting-serial (MCP)

Software diagnostics of the serial bus (RS-485, Modbus and other protocols) at the driver and MQTT level via `wb_*` MCP tools. Load this on: Modbus errors, CRC, timeouts, "device doesn't respond", "data not updating", slow polling, read/write errors.

**IMPORTANT: Act without pauses. Do NOT ask permission for each step — the user has ALREADY asked for diagnostics, that is the confirmation. Run ALL steps in sequence: logs → debug → scan → health. Do NOT stop with "want to run debug?" or "if you want, I can..." questions — just do it. Report at the end.**

## Tool routing

| Intent | Tool |
|--------|------|
| Collect raw RS-485 packets (enables debug, restarts driver, disables) | `wb_serial_debug` |
| Is slave_id alive (quick check) | `wb_modbus_probe` |
| What's on the bus (extended=Fast Modbus, standard=regular for third-party) | `wb_modbus_scan` (async via wb-device-manager) |
| Port parameters (baud, parity, stop) | `wb_modbus_ports` |
| Device template (for FW Version channel name) | `wb_modbus_template` |
| Current config to compare or edit | `wb_confed_load`, `wb_confed_save` |
| Driver logs | `wb_logs` `unit=wb-mqtt-serial` |
| Read/write registers outside the driver queue (requires stopping wb-mqtt-serial) | `wb_ssh_exec` `modbus_client` / `wb-modbus-scanner` |
| Read registers via the driver queue (safe) | `wb_ssh_exec` `modbus_client_rpc` |
| Read a channel value from MQTT | `wb_mqtt_read` |

## Start with this

1. **Device documentation** — always show the source URL. Sequence:
   - `WebFetch("https://wirenboard.com/wiki/<DeviceModel>")` — device page, "Known issues" section.
   - If nothing found there — `WebSearch("site:wirenboard.com/wiki/ <DeviceModel> <error>")` or `WebSearch("site:wiki.wirenboard.com <DeviceModel> <error>")`.
   - Look at the device changelog (`WebFetch` of changelog pages) — there are often ERRMODBUS codes and fixed bugs.
   - **Always cite the URL** the information came from.

2. Is the driver alive: `wb_ssh_exec` `systemctl is-active wb-mqtt-serial` (or `wb_failed` — if listed, all bad).

3. Logs — scale + last lines + histogram by slave_id. `wb_logs` supports `since`/`grep` — use them (the regex `device modbus:\\K\\d+` skips `[mqtt] connection lost`, `[serial client] Reading events failed` etc., so raw last lines are needed ALONGSIDE the histogram):

   ```
   wb_logs sn=<SN> unit=wb-mqtt-serial since="1 hour ago" priority=warning lines=30
   wb_logs sn=<SN> unit=wb-mqtt-serial since="1 hour ago" priority=warning grep="device modbus:" lines=500
   ```
   Histogram by slave_id — postprocess the second call's output locally (regex `device modbus:(\d+)` → count).

4. **Debug — raw packets. RUN IMMEDIATELY, DON'T ASK.** This is a safe operation — `wb_serial_debug` atomically enables debug in `/etc/wb-mqtt-serial.conf`, restarts the driver, collects journalctl over the window, **guaranteed** via `trap` to return `debug:false` and restart back (even on mid-failure). This is an **exception** to the general rule "ask before restarting wb-mqtt-serial" — restarts are part of the procedure.

   Debug duration: divide 18000 by the number of errors per hour (from step 3). Minimum 30, maximum 300 seconds. If errors <10/hour — set 120 (a long collection won't show anything on rare/transient issues anyway).

   Table:
   - <10 errors/hour → 120 sec
   - 10/hour → 18000/10 = 1800 → cap 300
   - 50/hour → 360 → cap 300
   - 100/hour → 180
   - 500/hour → 36
   - 1000+/hour → 18 → floor 30

   ```
   wb_serial_debug sn=<SN> duration=<DURATION>
   ```

   The tool returns `{jobId, logPath: /mnt/data/ai/wb-ai-skills/diag/debug-serial.log, message}`. Progress — `wb_job_status` / `wb_job_tail`. After completion:

   ```
   wb_read_file sn=<SN> path=/mnt/data/ai/wb-ai-skills/diag/debug-serial.log
   ```

   If the log is large (>64 KB) — `wb_read_file` will fail; use local `scp` outside MCP. **Right after the tool, verify that debug is actually off and the driver is alive:**

   ```
   wb_ssh_exec sn=<SN> cmd='grep -c "\"debug\":\\s*false" /etc/wb-mqtt-serial.conf; systemctl is-active wb-mqtt-serial'
   ```

   Should be `1` and `active`. If `debug:true` remained (trap didn't fire) — `wb_ssh_exec_async` `python3 -c "import json; c=json.load(open('/etc/wb-mqtt-serial.conf')); c['debug']=False; json.dump(c, open('/etc/wb-mqtt-serial.conf','w'), indent=2)" && systemctl restart wb-mqtt-serial`.

   If the error didn't reproduce in 2 minutes — tell the user: the issue is rare, debug is off.

5. **Bus scan** — who's there, who's missing, duplicates.

   - `wb_modbus_ports` — find parameters of **active** ports (not all physical `/dev/ttyRS485-*`/`/dev/ttyMOD*`, but only those the driver currently opens per the config).
   - `wb_modbus_scan path=<port> baud_rate=<baud> mode=all` — Fast Modbus scan. Take port parameters from `wb_modbus_ports` for the specific path. Finds **only WB and Onokom**. Third-party — invisible. **Can also silently miss live WB devices** (observed on WB-MAP6S — device is polled, MQTT channels update, but scan doesn't see it; `wb_modbus_probe` finds it immediately). If a device exists in `wb_confed_load` but not in `wb_modbus_scan` — be sure to check `wb_modbus_probe` before concluding "it died".

6. **WB device health** — uptime, power if needed. Via `modbus_client_rpc` (safe, goes through the driver queue):

   ```
   wb_ssh_exec sn=<SN> cmd='modbus_client_rpc -m rtu -a <slave> -t 3 -r 104 -c 2 -b <baud> -s <stop> -p <parity> <path>'
   wb_ssh_exec sn=<SN> cmd='modbus_client_rpc -m rtu -a <slave> -t 3 -r 121 -c 2 -b <baud> -s <stop> -p <parity> <path>'
   ```

   104-105 — uptime (u32, sec). 121-122 — Vsupply / Vmin (u16, mV) **only** on relays/dimmers/MCM. On WB-MAI/WB-MAP/some MR3, these registers map differently (input/measurement). If the value is implausible for voltage (5V on 24V supply) — for this model the register is different; see the device wiki page.

7. **Save the report** — `wb_write_file` `/mnt/data/ai/wb-ai-skills/diag/serial-diag.txt` with the report text.

## Device firmware version

If you need the firmware version of a specific WB device — **don't ask the user**, do this:

1. `wb_confed_load` `/etc/wb-mqtt-serial.conf` — find the device by slave_id, note `device_type` (e.g. `WB-MDM3`).
2. `wb_modbus_template device_type=<type>` — view the template. (Tool accepts only `device_type`/`mqtt-id`, case-insensitive. `wb_modbus_device_info` — for current firmware parameters by `device_id`.)
3. Among template channels find one whose name suggests firmware version: `FW Version`, `Firmware Version`, `SW Version`, `Serial`, etc. — the name can be anything, look by meaning.
4. In the driver config find this channel for the relevant device and set `"enabled": true`.
5. `wb_confed_save` with the updated full config.
6. `wb_mqtt_read` `/devices/<device_id>/controls/<channel_name>` (timeout 20 sec, to wait for publication after restart).

Example: for `wb-mdm3_57` the channel is named `FW Version`, for another device it may differ — always look in the template.

## Patterns: see → do

| Saw | Do |
|-----|-----|
| `invalid crc` in logs | `wb_serial_debug` → look at the raw packet. Bad CRC = noise/contact. Wrong slave_id = duplicate |
| `request timed out` | `wb_modbus_probe` → is it alive. If silent — physics, power, slave_id |
| `invalid data size` | `wb_modbus_scan` → look for slave_id duplicate. `wb_serial_debug` → extra bytes = collision |
| `rate limit exceeded` | Spread devices across ports, raise baud, disable extra channels |
| Device in scan but not in config | May be interfering! Add or physically disconnect |
| Device in config but not in scan | Off, broken wire, or third-party (scan doesn't see) |
| CRC on all devices | Noise, 120 Ω terminator, ground. Experiment: lower the speed |
| CRC on one | Connect with a short wire. If it works — the line |
| Other stop bits help | Mismatch of port and device parameters |
| Min voltage < 20V (reg 122) | Voltage drops → PSU, wire cross-section |
| Small uptime (reg 104-105) | Device was restarting → power |
| Exception code in debug | 1=illegal FC, 2=illegal addr, 3=illegal value, 4=device failure |
| Protocol isn't Modbus in config | `modbus_client_rpc` and scan won't help, only logs and debug |

## Tools

**modbus_client_rpc** (priority) — through the driver queue, safe. Run via `wb_ssh_exec`:

```
wb_ssh_exec sn=<SN> cmd='modbus_client_rpc -m rtu -a <slave> -t <FC> -r <reg> -c <count> -b <baud> -s <stop> -p <parity> <port>'
```

FC: 1=coils, 2=discrete, 3=holding, 4=input, 5=write coil, 6=write reg, 15=write coils, 16=write regs.

**`wb_modbus_probe`** — quick "is it alive" check.

**`wb_modbus_ports`** — port parameters.

**wb-modbus-scanner** — Fast Modbus utility (WB, Onokom). `wb_ssh_exec` `apt install wb-modbus-ext-scanner` (if not installed). Conflicts with the driver — requires stopping `wb-mqtt-serial` (coordinate with the user!).

```
wb_ssh_exec sn=<SN> cmd='systemctl stop wb-mqtt-serial && wb-modbus-scanner -d <port> -b <baud>; systemctl start wb-mqtt-serial'
```

**modbus_client** — direct access. Conflicts with the driver — also requires stopping `wb-mqtt-serial`.

## Useful WB device registers

| Register | What | Format |
|----------|------|--------|
| 104-105 | Uptime | u32, seconds (universal) |
| 110 | Baud rate | u16, abbreviated: 96=9600, 1152=115200 |
| 121 | Supply voltage | u16, mV — **only relays/dimmers/MCM** (different mapping on MAI/MAP/MR3) |
| 122 | Min voltage | u16, mV — same as 121 |
| 128 | Slave ID | u16 |
| 200-205 | Model | string |
| 270-271 | Serial number | u32 |

Broadcast write (slave_id 0) — change baud/address for all WB on the bus at once.

baud_rate `1152` = `115200` — abbreviated form, NOT an error.

## Experiments (backup + coordinate with the user)

Before experiments:

```
wb_ssh_exec sn=<SN> cmd='cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)'
```

- **Stop bits**: try 1 and 2 via `modbus_client_rpc -s 1` / `-s 2`.
- **Speed**: broadcast `modbus_client_rpc -a 0 -t 6 -r 110 ... 96` → port change via `wb_confed_save`. Errors gone = cable/termination.
- **Isolation**: `wb_confed_load` → `"enabled": false` for the suspect device → `wb_confed_save`. Errors gone for the rest = this device interferes.
- **Timeouts**: `response_timeout_ms`, `guard_interval_us` in port config.

**Roll everything back after experiments.**

## Gotchas

- `modbus_client`/`wb-modbus-scanner` without stopping the driver → spurious errors.
- Debug forgotten — `wb_serial_debug` turns it off and restores the config itself; don't touch via `wb_confed_save` by hand.
- `wb_modbus_scan` → only WB and Onokom.
- Wrong baud → COMPLETELY silent. Wrong stop bits → flaky errors.
- RS-485 in star topology works on short distances; for problems — recommend a chain (daisy chain).

## Documentation

- <https://wiki.wirenboard.com/wiki/RS-485>
- <https://wiki.wirenboard.com/wiki/Modbus>
- <https://wiki.wirenboard.com/wiki/Common_Modbus_Registers>
- <https://wiki.wirenboard.com/wiki/How_to_diagnose>
- <https://github.com/wirenboard/wb-modbus-ext-scanner/blob/main/docs/protocol.ru.md>
