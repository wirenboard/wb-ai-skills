---
name: hardware-modules
description: Configuring WB expansion modules (MOD1-4, WBIO, RS-485, Zigbee, CAN) via confed RPC.
allowed-tools: Bash Read Write WebFetch
---

# hardware-modules

Configuring internal expansion modules of a Wiren Board controller.

## Architecture

- **Config:** `/etc/wb-hardware.conf` (JSON)
- **Service:** `wb-hwconf-manager` — applies Device Tree overlays
- **Editing:** via confed RPC (don't edit the file directly!)

## Slots

The exact set of slots depends on the platform (wb6/wb7/wb8) and revision. **Take it from the `schema` of the `Editor/Load` response** — it reflects the actual hardware. Typical picture:

| Slot in `content` | What it is | Possible port |
|------------------|---------|----------------|
| `wb84-mod1`..`wb84-mod3` (on wb8) or `mod1`..`mod4` (on wb7) | Internal UART/GPIO slots. Some slots are UART-only, some GPIO-only (e.g. `wb84-mod1` without UART) | `/dev/ttyMOD<N>` if the module is UART (Zigbee, CAN-UART, RS-485, RS-232, GPS) |
| `wb84-rs485-1`, `wb84-rs485-2` | Built-in RS-485 with terminator | `/dev/ttyRS485-1`, `/dev/ttyRS485-2` |
| `wb84-extio1`..`wb84-extio8` | GPIO for WBIO modules (relays, dry contacts, SSR) | — (no tty) |
| `wb84-w1`, `wb84-w2` | W1/W2 terminals in 1-Wire master mode | — (via w1-bus, not tty) |
| `wb84-wbmz5` | Backup power slot (BRP) | — |
| `wb72-wbc` | Modem slot (on supported platforms) | — (modem) |

The prefix (`wb84-*` for wb8, no prefix for wb7, etc.) varies between revisions — don't hard-code a specific ID, pick by `schema.title` / `description`.

## Reading configuration

```bash
# Load current config + schema via confed RPC
ssh root@<HOST> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/confed/Editor/Load/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/confed/Editor/Load/${ID}" -m "{\"id\":\"${ID}\",\"params\":{\"path\":\"/etc/wb-hardware.conf\"}}"
  wait $SUB_PID
'
```

The response contains `configPath`, `content` (config object) and `schema` (JSON Schema with all modules).

## Installing a module

**Step 0:** Ask the user which slot the module is physically inserted in. Don't pick yourself!

**Step 1:** Read the config (above) — determine `module` from `schema`. Human-readable description is in `content.modules[].description` (not in `schema.definitions`, which only has technical discrimination by `id`).

Real IDs from wb-2507/wb8 firmwares — for orientation, **don't copy blindly**:

| Module | module ID (examples) |
|--------|---------------------|
| Zigbee | `wbe2r-r-zigbee` |
| RS-232 | `wbe2-i-rs232` |
| RS-485 (built-in) | `wb67-can-rs485` |
| RS-485 (external slot, isolated) | `wbe2-i-rs485-iso` |
| CAN | `wb67-can`, `wbe-i-can-iso`, `wb67-can-uart` |
| 1-Wire | `wb6-wx-1wire` |

> Exact IDs depend on platform and revision. **Always** take from the schema response — different revisions have different `wbe2-*` / `wb67-*` / `wb84-*` packages.

**Step 2:** Modify `content` — set `module` in the desired slot. Save via confed:

```bash
ssh root@<HOST> bash -c '
  ID=$(cat /dev/urandom | tr -dc a-z0-9 | head -c8)
  mosquitto_sub -t "/rpc/v1/confed/Editor/Save/${ID}/reply" -C 1 -W 15 &
  SUB_PID=$!
  sleep 0.3
  mosquitto_pub -t "/rpc/v1/confed/Editor/Save/${ID}" -m "{\"id\":\"${ID}\",\"params\":{\"path\":\"/etc/wb-hardware.conf\",\"content\":<full JSON>}}"
  wait $SUB_PID
'
```

**Step 3:** Verify — but only if installing a UART module (Zigbee/CAN-UART/RS-232/RS-485/GPS):
```bash
ssh root@<HOST> 'ls -la /dev/ttyMOD<N>'
```
For GPIO/1-Wire/extio/WBMZ5/modem the `/dev/ttyMOD*` port won't appear — that's **normal**, don't confuse with an installation error. For 1-Wire — verify via `ls /sys/bus/w1/devices/`. For extio/WBIO — via `mosquitto_sub /devices/+/meta/name` (a new device will appear in MQTT).

## Pitfalls

- **Don't edit `/etc/wb-hardware.conf` via ssh directly** — only confed RPC
- **Module IDs** depend on revision — always take from schema
- After installing Zigbee → set up zigbee2mqtt (`/software-install`)
- Changing the module in a slot — the old one is deinitialized, devices disappear

## Documentation

- <https://wiki.wirenboard.com/wiki/Internal_modules>
- <https://wiki.wirenboard.com/wiki/WBIO>
