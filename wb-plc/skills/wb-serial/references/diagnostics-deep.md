# Deep serial diagnostics

The SKILL.md has the 7-step hot-path sequence. This reference covers the long-form details: tools, the debug-duration table, useful registers, experiments, the saw → do table.

## Debug duration heuristic

Divide 18000 by the number of errors per hour (from the journal step). Minimum 30, maximum 300. If <10 errors/h — set 120 sec.

| Errors/hour | Duration |
|---|---|
| <10 | 120 sec |
| 10-59 | 300 sec (cap) |
| 60-99 | 300 sec (cap) |
| 100 | 180 sec |
| 500 | 36 sec → floor 30 sec |
| 1000+ | 18 sec → floor 30 sec |

## Running `wb-cli serial-debug`

Safe operation — `wb-cli serial-debug` enables `wb-mqtt-serial`'s `Debug` control, captures the journal for a window, then restores it even if the capture fails. No driver restart, no config edit, no `trap` to maintain by hand.

```bash
ssh root@<HOST> wb-cli --json serial-debug --port /dev/ttyRS485-1 --seconds <DURATION>
```

Returns the journal entries collected during the window as JSON (`.data.entries`). For long captures (>30 s) wrap it in a background job so SSH doesn't time out:

```bash
ssh root@<HOST> wb-cli --json job run serial-debug "wb-cli --json serial-debug --port /dev/ttyRS485-1 --seconds <DURATION> > /mnt/data/ai/wb-ai-skills/diag/debug-serial.json"
ssh root@<HOST> wb-cli --json job wait serial-debug
scp root@<HOST>:/mnt/data/ai/wb-ai-skills/diag/debug-serial.json /tmp/debug-serial.json
```

**Verify debug control is off afterwards** (in case the job was killed mid-flight):

```bash
ssh root@<HOST> wb-cli --json mqtt read '/devices/wb-mqtt-serial/controls/Debug'
```

Should return `"0"`. If `"1"` — clear it with `wb-cli mqtt write /devices/wb-mqtt-serial/controls/Debug/on 0`.

### Fallback (older firmware without `Debug` control)

Edit `/etc/wb-mqtt-serial.conf` via confed to set `debug:true`, restart the driver, sleep, collect the journal, restore. **Keep the `trap` — without it a hung restart leaves the controller in debug mode, filling the disk.**

## Bus scan and ports

```bash
ssh root@<HOST> wb-cli --json serial ports                                  # active ports the driver serves
ssh root@<HOST> wb-cli --json serial wb-scan --port /dev/ttyRS485-1         # Fast Modbus (WB+Onokom)
ssh root@<HOST> wb-cli --json serial wb-scan --slow --port /dev/ttyRS485-1 --timeout 300   # exhaustive UART poll (third-party)
ssh root@<HOST> wb-cli --json serial wb-scan --bootloader --port /dev/ttyRS485-1            # devices stuck in bootloader
```

`serial ports` returns only **active** ports — the same list `wb-cli serial wb-scan` iterates over. If a port is missing, `wb-mqtt-serial` rejected its stanza (schema validation) — repair with `wb-cli confed load /etc/wb-mqtt-serial.conf` + `confed save`. For a full filesystem-level list — `ls /dev/ttyRS485-* /dev/ttyMOD* /dev/ttyUSB*`.

## WB device health — uptime + power

```bash
# Uptime (regs 104-105) — on all WB devices with WB-MS-protocol firmware:
ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t 3 -r 104 -c 2 -b <baud> -s <stop> -p <parity> <path>"
# Vsupply / Vmin (regs 121-122, mV) — on relays/dimmers/MCM:
ssh root@<HOST> "modbus_client_rpc -m rtu -a <slave> -t 3 -r 121 -c 2 -b <baud> -s <stop> -p <parity> <path>"
```

**Registers 121-122 are not universal** — on WB-MAI6/WB-MAP6S and some MR3 they may return other values. If implausible — see the device wiki page.

## Save the report

```bash
echo '<report text>' | ssh root@<HOST> 'cat > /mnt/data/ai/wb-ai-skills/diag/serial-diag.txt'
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

**device/Probe** — quick "alive?" check.

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

## Reading device parameters during diagnostics

When you suspect misconfigured firmware settings, read them directly from hardware:

```bash
ssh root@<HOST> wb-cli --json serial fw-params <slave_id>
```

Returns the current `parameters` values (e.g. input modes, relay behaviours, thresholds). Compare with expected values from the template or user settings. To apply a fix in-place without editing the config file:

```bash
ssh root@<HOST> wb-cli --json serial fw-params <slave_id> <param>=<value>
```

## Experiments (backup + agree with the user)

Before experiments:

```bash
ssh root@<HOST> "cp /etc/wb-mqtt-serial.conf /etc/wb-mqtt-serial.conf.bak-$(date +%s)"
```

- **Stop bits**: try 1 and 2 via `modbus_client_rpc -s 1` / `-s 2`
- **Speed**: broadcast `modbus_client_rpc -a 0 -t 6 -r 110 ... 96` → change port via confed. Errors gone = cable/termination
- **Isolation**: `wb-cli confed load /etc/wb-mqtt-serial.conf` → flip the suspect device's `"enabled": false` → `wb-cli confed save`. Errors gone on the rest = this device interferes
- **Timeouts**: `response_timeout_ms`, `guard_interval_us` in port config. If your own service depends on these values, don't copy them as constants — see "Constants that mirror controller settings" in the wb-dev skill

**Roll everything back after experiments.**
