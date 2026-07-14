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

## wb-cli — primary tool

`wb-cli serial` wraps every wb-mqtt-serial / wb-device-manager RPC the diagnostics flow needs; prefer it to raw MQTT RPCs.

```bash
ssh root@<HOST> wb-cli --json serial wb-scan --port /dev/ttyRS485-1     # bus scan (Fast Modbus)
ssh root@<HOST> wb-cli --json serial wb-scan --slow --timeout 300       # exhaustive UART poll
ssh root@<HOST> wb-cli --json serial wb-scan --bootloader               # devices in bootloader mode
ssh root@<HOST> wb-cli --json serial config                            # what's in /etc/wb-mqtt-serial.conf
ssh root@<HOST> wb-cli --json serial ports                              # ports the driver currently serves
ssh root@<HOST> wb-cli --json serial fw-params 52                   # current firmware settings
ssh root@<HOST> wb-cli --json serial fw-params 52 in0_mode=1     # update firmware settings
ssh root@<HOST> wb-cli --json serial-debug --port /dev/ttyRS485-1 --seconds 60
ssh root@<HOST> wb-cli --json dev wb-mr6c_52                            # live values from the device
```

## MQTT RPC via Bash — base pattern (fallback)

Use only for RPCs that wb-cli does not yet wrap (custom drivers, ad-hoc exploration). Anything covered by `wb-cli serial …` should go through wb-cli.

```bash
ssh root@<HOST> 'CID=ai-$(date +%s)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " "); mosquitto_sub -t "/rpc/v1/<driver>/<service>/<method>/$CID/reply" -C 1 -W <timeout> & sleep 0.2; mosquitto_pub -t "/rpc/v1/<driver>/<service>/<method>/$CID" -m '"'"'{"id":1,"params":{...}}'"'"'; wait'
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

For the full template JSON layout (minimal example, channel fields, parameters, groups, translations, endianness, string/varstring) — see **`references/template-format.md`**.

For translation-key style (synthetic key vs English-text key), en/ru capitalization rules, json-editor/confed schema i18n, and the config-key ↔ translation-key ↔ enum-value ↔ label coherence check — see **`references/i18n-naming.md`**.

For the 6-step creation workflow, the `fw-params` read/write flow, listing devices and ports, and device firmware-version lookup — see **`references/template-workflow.md`**.

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

# Add all found devices across every port the scan touched (one call)
ssh root@<HOST> wb-cli --json serial add-devices

# Or limit to a single port
ssh root@<HOST> wb-cli --json serial add-devices --port /dev/ttyRS485-1
```

`add-devices` reads the retained wb-device-manager state — so you can run any scan type (extended or slow) and then add without re-scanning. Devices already in config are skipped.

### Add a single device by model (no scan needed)

```bash
ssh root@<HOST> wb-cli --json serial add-devices \
  --port /dev/ttyRS485-1 --device-type WB-MAI6 --slave-id 19
```

For the automatic-fixups table (baud, duplicate slave_id, conflict resolution) and the `add-devices` result shape — see **`references/template-workflow.md`**.

## Bus-level writes — `slave_id` and `baud rate`

WB devices expose two bus-level registers that aren't template parameters — `slave_id` (reg 128) and `baud rate / 100` (reg 110). Dedicated wb-cli shortcuts:

```bash
# Change a device's slave_id
ssh root@<HOST> wb-cli --json serial wb-set-slave-id 5 19 --port /dev/ttyRS485-1

# Collision-safe via WB Fast Modbus by SN (no need to know the current address)
ssh root@<HOST> wb-cli --json serial wb-set-slave-id 5 19 --port /dev/ttyRS485-1 --sn 0x00020B86

# Change baud rate; speak to the device at its current baud
ssh root@<HOST> wb-cli --json serial wb-set-baud 5 9600 --port /dev/ttyRS485-1 --baud 19200
```

**Caveat — WB-only.** Both use the *WB Common Modbus Registers* convention. Won't work for non-Modbus devices on the same RS-485 (Энергомера IEC-61107, DOOYA) or third-party Modbus devices that change slave_id via a different register. The `add-devices` baud-fixup and address-collision recovery use the same internally, so they're also WB-only.

## Sending raw Modbus PDUs

```bash
# Read 1 holding register (FC3, reg 110)
ssh root@<HOST> wb-cli --json serial send-modbus --port /dev/ttyRS485-1 --slave 5 --fc 3 --reg 110

# Read 10 input registers from a third-party device at 19200
ssh root@<HOST> wb-cli --json serial send-modbus --port /dev/ttyRS485-1 --slave 12 --fc 4 \
    --reg 0 --count 10 --baud 19200

# Write a single holding register (FC6)
ssh root@<HOST> wb-cli --json serial send-modbus --port /dev/ttyRS485-1 --slave 5 --fc 6 \
    --reg 128 --value 19
```

Supports FC3 / FC4 / FC6. For Fast Modbus or other FCs use raw `serial send`. For Modbus devices only; non-Modbus protocols won't answer.

## Firmware update — `serial wb-fw`

```bash
ssh root@<HOST> wb-cli --json serial wb-fw check 4 --port /dev/ttyRS485-1          # one device
ssh root@<HOST> wb-cli --json serial wb-fw check                                    # every device
ssh root@<HOST> wb-cli --json serial wb-fw update 4 --port /dev/ttyRS485-1 --wait   # flash blocking
ssh root@<HOST> wb-cli --json serial wb-fw update --all --background \
    --output /mnt/data/ai/wb-cli/fw-$(date +%s).json                                # flash all in background
ssh root@<HOST> wb-cli --json serial wb-fw restore 4 --port /dev/ttyRS485-1 --wait  # recover stuck bootloader
ssh root@<HOST> wb-cli mqtt sub /wb-device-manager/firmware_update/state            # progress feed
```

## Loading / testing without restart

```bash
ssh root@<HOST> 'systemctl restart wb-mqtt-serial'
ssh root@<HOST> 'journalctl -u wb-mqtt-serial -n 50 --no-pager | grep -iE "(template|<device.id>)"'
```

---

# Part 2 — Diagnostics

## Start with this — 7-step sequence

1. **Documentation** — `WebFetch("https://wirenboard.com/wiki/<DeviceModel>")` for "Known issues"; if nothing — `WebSearch("site:wirenboard.com/wiki/ <DeviceModel> <error>")`. Always cite the URL.

2. **Driver alive?** `ssh root@<HOST> "systemctl is-active wb-mqtt-serial"`.

3. **Logs — count + tail + histogram by slave_id**:
   ```bash
   ssh root@<HOST> "journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | wc -l; echo ---; journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | tail -30"
   ssh root@<HOST> "journalctl -u wb-mqtt-serial -p warning --since '1 hour ago' --no-pager | grep -oP 'device modbus:\\K\\d+' | sort | uniq -c | sort -rn"
   ```

4. **Debug — raw packets. RUN IMMEDIATELY, DON'T ASK.** Duration depends on error rate from step 3:
   ```bash
   ssh root@<HOST> wb-cli --json serial-debug --port /dev/ttyRS485-1 --seconds <DURATION>
   ```
   For the duration heuristic table, the long-capture wrapping in a wb-cli job, and the `Debug` post-condition check — see **`references/diagnostics-deep.md`**.

5. **Bus scan** — `wb-cli --json serial wb-scan --port /dev/ttyRS485-1` (Fast Modbus) or `--slow` for third-party. `serial ports` for active ports.

6. **WB device health** — uptime regs 104-105, supply / min voltage regs 121-122 on relays/dimmers/MCM.

7. **Save the report** to `/mnt/data/ai/wb-ai-skills/diag/serial-diag.txt`.

For full step bodies (debug-duration table, raw-packet capture wrapping, health-check commands, save-the-report snippet) — see **`references/diagnostics-deep.md`**.

For the **saw → do** patterns table, the **tools** section (modbus_client_rpc, device/Probe, wb-modbus-scanner, modbus_client), the **useful WB device registers** table, and **experiments** (stop bits, speed, isolation, timeouts) — also in `references/diagnostics-deep.md`.

## Fast Modbus (WB extension protocol)

WB devices support a Modbus-RTU extension that adds: scan-by-SN, targeted-PDU-by-SN (for slave_id collisions), and event push (low-latency diagnostics). All frames use broadcast address `0xFD` and command byte `0x46`. Use it when scan finds two devices with the same slave_id, or when a device is in scan but unresponsive to `modbus_client_rpc`.

For the frame types table, exact byte sequences (change slave_id by SN, change baud by SN), the `port/Load` RPC envelope, and when-to-use guidance — see **`references/fast-modbus.md`**.

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

## What the agent does NOT do

- **Edit `/etc/wb-mqtt-serial.conf` manually** (or via raw confed API). Use `wb-cli serial add-devices` — it fills required template params from defaults; manual edits cause `ports/Load` to return `[]` and break all bus scans.
- **Run `modbus_client` / `wb-modbus-scanner`** while `wb-mqtt-serial` is active. They contend for the same port → false errors. Stop the driver first (agree with the user — that pauses ALL polling).
- **Leave debug mode on after a diagnostic capture.** `wb-cli serial-debug` restores it automatically; raw-restart flows must re-disable explicitly or the journal fills the disk.
- **Use slave_id 0 outside of the specific broadcast write** for "change baud/address for ALL WB devices at once". Slave_id 0 = broadcast — every device responds (or none reply).
- **Pick `word_order: little_endian` by default.** Modbus byte order is big-endian — only override when a multi-register value is observably wrong (jumps by 65535×).
- **Override a packaged template by reusing its `device_type`.** Custom templates with the same `device_type` silently win; use a prefix (`ACME-`, `BIDIR-`) to avoid confusion.

## When to ask the user

- About to broadcast-write reg 110 or 128 (slave_id 0) — confirm; this hits every WB device on the bus.
- About to firmware-update a device while production polling is happening on the same bus — confirm the timing window.
- Experiments (stop bits, baud, port timeouts) — confirm the rollback plan; back up `/etc/wb-mqtt-serial.conf` first.
- Adding a custom protocol (non-Modbus) device to the same port as Modbus devices — confirm the per-device polling priorities; non-Modbus drivers can block Modbus scans.
- A scan shows duplicate slave_ids — surface the candidates and confirm which one keeps the address.
- About to enable a heavy polling channel (high `read_rate_limit_ms` but slow device) — confirm; rate-limit errors will start firing.

## Documentation

- Template format: <https://github.com/wirenboard/wb-mqtt-serial/blob/master/docs/template.md>
- RS-485: <https://wiki.wirenboard.com/wiki/RS-485>
- Modbus: <https://wiki.wirenboard.com/wiki/Modbus>
- Common registers: <https://wiki.wirenboard.com/wiki/Common_Modbus_Registers>
- Diagnostics guide: <https://wiki.wirenboard.com/wiki/How_to_diagnose>
- Modbus FC spec: <https://modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf>
- Examples: `/usr/share/wb-mqtt-serial/templates/` on the controller (250+ templates).
