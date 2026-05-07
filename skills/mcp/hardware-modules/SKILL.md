---
name: hardware-modules
description: Configuring WB expansion modules (MOD1-4, WBIO, RS-485, Zigbee, CAN) via MCP — wb_confed_load/save for /etc/wb-hardware.conf.
allowed-tools: Bash Read Write WebFetch
---

# hardware-modules (MCP)

Configuring internal expansion modules of a Wiren Board controller via `wb_confed_*` MCP tools.

## Architecture

- **Config:** `/etc/wb-hardware.conf` (JSON).
- **Service:** `wb-hwconf-manager` — applies Device Tree overlays.
- **Editing:** via `wb_confed_save` (don't write the file directly via `wb_write_file` — `wb_confed_save` validates and atomically restarts dependent services).

## Tool routing

| Intent | Tool |
|--------|------|
| Read `/etc/wb-hardware.conf` (with JSON Schema) | `wb_confed_load path=/etc/wb-hardware.conf` |
| Write config (validation + apply) | `wb_confed_save` |
| Which ports appeared (`/dev/ttyMODn`, `/dev/ttyRS485-n`) | `wb_ssh_exec` `ls -la /dev/ttyMOD* /dev/ttyRS485-*` |
| Module driver logs | `wb_logs unit=<unit>` |
| Service state after change | `wb_failed` |

## Slots

The exact set depends on the platform (wb6/wb7/wb8) and revision — **take it from the `schema`** returned by `wb_confed_load`. Typical picture:

| Slot in `content` | What it is | Possible port |
|-------------------|-----------|---------------|
| `mod1`..`modN` or `wb84-mod1`..`wb84-mod3` | Internal UART/GPIO slots. Some UART-only, some GPIO-only | `/dev/ttyMOD<N>` if module is UART (Zigbee, CAN-UART, RS-485, RS-232, GPS) |
| `wb84-rs485-1`, `wb84-rs485-2` | Built-in RS-485 with terminator | `/dev/ttyRS485-1`, `/dev/ttyRS485-2` |
| `wb84-extio1`..`wb84-extio8` | GPIO for WBIO modules (relays, dry contacts, SSR) | — (no tty) |
| `wb84-w1`, `wb84-w2` | W1/W2 terminals in 1-Wire master mode | — (via w1-bus) |
| `wb84-wbmz5` | Backup power BRP slot | — |
| `wb72-wbc` | Modem slot | — (modem) |

The ID prefix (`wb84-*` for wb8 etc.) varies between revisions — don't depend on it, choose by `schema.title`/`description`.

## Reading the configuration

`wb_confed_load path=/etc/wb-hardware.conf` returns `configPath`, `content` (config object) and `schema` (JSON Schema with all modules). Take the precise module IDs for the current board revision from the schema.

## Installing a module

**Step 0:** Ask the user which slot the module is physically inserted in. Don't choose yourself!

**Step 1:** `wb_confed_load` — determine the valid `module` value from `schema`. The human-readable module description is in `content.modules[].description`.

Real IDs from wb-2507/wb8 firmware — for reference, **don't copy blindly**:

| Module | module ID (examples) |
|--------|----------------------|
| Zigbee | `wbe2r-r-zigbee` |
| RS-232 | `wbe2-i-rs232` |
| RS-485 (built-in) | `wb67-can-rs485` |
| RS-485 (external slot, isolated) | `wbe2-i-rs485-iso` |
| CAN | `wb67-can`, `wbe-i-can-iso`, `wb67-can-uart` |
| 1-Wire | `wb6-wx-1wire` |

> Exact IDs depend on platform and revision. **Always** take from the `schema` of the response — different revisions have different `wbe2-*` / `wb67-*` / `wb84-*` packages.

**Step 2:** Modify `content` — set `module` in the desired slot. Save:

```
wb_confed_save sn=<SN> path=/etc/wb-hardware.conf content=<full JSON>
```

**Step 3:** Verify — but only if installing a UART module (Zigbee/CAN-UART/RS-232/RS-485/GPS):

```
wb_ssh_exec sn=<SN> cmd='ls -la /dev/ttyMOD<N>'
```

For GPIO/1-Wire/extio/WBMZ5/modem, the `/dev/ttyMOD*` port won't appear — this is **normal**, don't confuse with installation error. For 1-Wire — `wb_ssh_exec` `ls /sys/bus/w1/devices/`. For extio/WBIO — `wb_mqtt_devices` (a new device will appear in `/devices/+/meta/name`).

In any case — `wb_failed` to make sure dependent services didn't fail.

**Step 4:** Switching the MOD1-4 profile may require a **controller reboot** — `wb_confed_save` restarting `wb-hwconf-manager` doesn't always cover applying a new overlay. If the port doesn't appear — warn the user and propose `reboot` (with confirmation).

## Gotchas

- **Don't write `/etc/wb-hardware.conf` via `wb_write_file`** — only `wb_confed_save`. Broken JSON can leave the controller without network after `wb-hwconf-manager` restart.
- **Module IDs** depend on revision — always take from `schema`, not from memory.
- After installing Zigbee → configure zigbee2mqtt (`/software-install`).
- Changing the module in a slot — the old one is deinitialized, devices disappear.

## Documentation

- <https://wiki.wirenboard.com/wiki/Internal_modules>
- <https://wiki.wirenboard.com/wiki/WBIO>
