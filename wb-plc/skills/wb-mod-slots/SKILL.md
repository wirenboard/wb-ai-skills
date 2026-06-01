---
name: wb-mod-slots
description: "Reconfigure WB controller MOD slots via wb-hwconf-helper — switch a slot away from its default (usually RS-485) into raw UART (/dev/ttyMODx), bit-banged I2C (/dev/i2c-modN), CAN, SPI, or 1-Wire by loading the matching device-tree overlay module. Use when user wants to repurpose a MOD slot, expose UART/I2C on MOD pins for chip programming or a non-Modbus device, mentions wb-hwconf-helper, /etc/wb-hardware.conf, wbe2x-generic-uart, wbe2x-generic-i2c, or sees /dev/ttyMOD3 give `stty: Input/output error`."
allowed-tools: Bash Read Write WebFetch
---

# wb-mod-slots

Operate the per-slot hardware configuration on WB6/WB7/WB8 controllers — MOD1..MOD4 (internal WBE2 slots) and rs485-1..rs485-2. The slot's mode (RS-485, raw UART, bit-banged I2C, CAN, ...) is selected at runtime by loading a device-tree overlay through `wb-hwconf-helper`. Sister skill to `wb-serial`, which handles Modbus on top of the default RS-485 mode.

## CRITICAL RULES

> **Don't write `/etc/wb-hardware.conf` blindly.** The file is the persistent config consumed at boot. A bad JSON or a wrong slot-id locks the slot into a non-working state on every reboot. For testing, prefer the **runtime** `init`/`deinit` path — it doesn't touch the conf file.

> **`init` and `deinit` need the FULL board-prefixed slot-id** (e.g. `wb85-mod3`, not `mod3`). The short `mod3` form only works through `config-apply` against `/etc/wb-hardware.conf`. If `wb-hwconf-helper` complains "Slot definition file …/slots/mod3.def not found", you forgot the prefix.

> **After `init`, expect a brief glitch on the slot's lines.** Don't switch modes while another MCU on the wire is mid-transaction — pinmux flips can clock random bits and corrupt the peer's state.

> **`<HOST>` in examples** means `wirenboard-<SN>.local` (substitute the controller's mDNS name).

## When to load this skill

- User wants to expose raw UART or I2C on a MOD slot for a custom device, MCU programming, GPIO bit-bang, or one-off bench work.
- `stty -F /dev/ttyMOD3` returns `Input/output error` even though the device file exists (= pinmux not applied yet).
- `wb-mqtt-serial` is configured to use `/dev/ttyMODx` but the port refuses to open.
- User mentions `wb-hwconf-helper`, `/etc/wb-hardware.conf`, `wbe2x-generic-uart`, `wbe2x-generic-i2c`, `i2c-gpio`, MOD slot mode, repurpose MOD3 / MOD4.
- User asks where `/dev/i2c-modN` came from or how to make one appear.

Stay out and hand off when:
- It's actually a Modbus/RS-485 diagnostics question on the default mode → `wb-serial`.
- Network adapters / WiFi / 4G → `wb-network`.

## Architecture — what a MOD slot is

A MOD slot is an internal WBE2 connector on the controller. The CPU exposes a UART (or alternate functions: I2C, SPI, GPIO) on the slot's pins. **What runs on those pins is decided at boot by an applied device-tree overlay.** No overlay → pins are bare GPIOs in input mode → `/dev/ttyMODx` exists as a udev symlink but the underlying 8250 UART driver fails to talk to dead pinmux.

Layout on disk:

```
/etc/wb-hardware.conf                              # persistent user config (JSON)
/var/lib/wirenboard/hardware.state                 # current slot→module mapping (runtime)
/usr/share/wb-hwconf-manager/
├── boards/<board>.conf                            # default modules per slot for this board
├── slots/<board>-<slot>.def                       # slot pin map (e.g. wb85-mod3.def)
└── modules/<module>.dtso  +  <module>.sh          # overlay sources + add/remove hooks
/sys/firmware/devicetree/base/model                # current board hint
```

Board hint examples: `Wiren Board rev. 8.5.1 (T507)` → `boards/wb85xm.conf`. The mapping from DT compatible to `boards/*.conf` is in `wb-hwconf-manager/config.py`.

## Tool: wb-hwconf-helper

```
wb-hwconf-helper init <slot-id> <module>   # apply overlay now (non-persistent)
wb-hwconf-helper deinit <slot-id>           # roll back the active overlay on a slot
wb-hwconf-helper config-apply               # diff /etc/wb-hardware.conf vs current, apply
wb-hwconf-helper load-overlay <fname>       # apply a standalone DTS overlay
wb-hwconf-helper unload-overlay <fname>     # remove one
wb-hwconf-helper confed-tojson              # for the web editor
wb-hwconf-helper confed-fromjson            # for the web editor
```

`<slot-id>` for `init`/`deinit` is the **full** id from `boards/<board>.conf` (`wb85-mod3`, `wb84-rs485-1`, `wb67-w1`, …). The web editor uses the short form (`mod3`) and resolves it through the board file; the CLI does not.

## Workflow: switch a MOD slot's mode (runtime, recommended)

Switch MOD3 from default RS-485 to raw UART:

```bash
ssh root@<HOST> sudo wb-hwconf-helper init wb85-mod3 wbe2x-generic-uart
ssh root@<HOST> stty -F /dev/ttyMOD3        # should succeed now
```

Switch the same slot to bit-banged I2C:

```bash
ssh root@<HOST> sudo wb-hwconf-helper deinit wb85-mod3
ssh root@<HOST> sudo wb-hwconf-helper init wb85-mod3 wbe2x-generic-i2c
ssh root@<HOST> ls /dev/i2c-mod3 /dev/i2c-*  # the slot now appears as an i2c-gpio adapter
```

This path **does not** write to `/etc/wb-hardware.conf`. On the next reboot the slot reverts to the board default — desirable for bench tests, not for production use.

## Workflow: persistent change (production)

Edit `/etc/wb-hardware.conf`:

```json
{
  "slots": [
    { "slot_id": "mod3", "module": "wbe2x-generic-uart" }
  ]
}
```

Note: short `slot_id` here ("mod3"), not the board-prefixed form. The board file resolves it.

Apply:

```bash
ssh root@<HOST> sudo wb-hwconf-helper config-apply
```

`config-apply` diffs the new config vs `/var/lib/wirenboard/hardware.state`, calls `deinit`+`init` for each changed slot, and runs `module add/remove` hooks. Survives reboot.

## Module catalogue (most common)

Names match files in `/usr/share/wb-hwconf-manager/modules/`. List the full set per board with `ls /usr/share/wb-hwconf-manager/modules/` on the controller.

| Module                  | Exposes                                                  | Notes |
| ----------------------- | -------------------------------------------------------- | ----- |
| `wbe2x-generic-uart`    | `/dev/ttyMODn` — raw UART on the slot's TX/RX            | CPU UART, 3.3 V LVCMOS on T507. Check schematic for older boards. |
| `wbe2x-generic-i2c`     | `/dev/i2c-modN` — bit-banged `i2c-gpio`                  | TX→SDA, RX→SCL per `wbe2-i2c.dtsi`. ~100 kHz, no internal pull-ups. |
| `wb67-can-rs485`        | RS-485 on rs485-1/2 slots                                | Default for `rs485-*` slots. |
| `wbe2-i-rs485-iso`      | Isolated RS-485 via WBE2-I-RS-485-ISO                    | For external WBE2 ISO modules. |
| `wbe2-i-rs232`          | RS-232                                                   | |
| `wbe2-i-can`            | CAN                                                      | Slot must be wbe2-i-can compatible (check `boards/<board>.conf`). |
| `wbe2-i-knx`            | KNX                                                      | |
| `wb6-wx-1wire`          | 1-Wire on w1/w2 terminal mode                            | |
| `wbe2-i-w1` / `-w1-gpio`| 1-Wire on MOD slot                                       | |
| `wbe2-i-opentherm`      | OpenTherm                                                | |

If `init` fails with a DTS parse error, the slot likely doesn't match the module's `compatible-slots` — see the capability check below.

## Slot capabilities — what fits where

**Slots on the same board are NOT all equivalent.** Each slot has a `compatible: [...]` list of tags; each module declares a single `compatible-slots = "<tag>"` string. A module loads on a slot iff the module's tag is in the slot's list.

Example on wb8.5 (`/usr/share/wb-hwconf-manager/boards/wb85x.conf`):

| Slot              | Compat tags                                                                       | I2C? | UART? |
| ----------------- | --------------------------------------------------------------------------------- | :--: | :---: |
| `mod1` / `mod2`   | wbe2, wbe2-gpio, wbe3-reduced-uart, wbe3-wbec-only, wbe2-i-can                    | ✗    | ✓     |
| `mod3` / `mod4`   | wbe2, wbe2-gpio, **wbe2-i2c**, **wbe3-reduced**, wbe3-reduced-uart, wbe2-i-can    | ✓    | ✓     |
| `rs485-1` / `-2`  | wb67-rs485                                                                        | ✗    | RS-485 only |

So `wbe2x-generic-i2c` (`compatible-slots = wbe3-reduced`) **loads on mod3/mod4 but fails on mod1/mod2** — the agent must check capability before suggesting a slot. Same for analog modules (`wbe2-ai-cm-1`, `wbe2-ao-10v-2`) and RTC.

Run this on the controller to print the per-slot compatibility matrix for the current board:

```bash
ssh root@<HOST> python3 << 'PY'
import json, os, re, sys
sys.path.insert(0, "/usr/lib/wb-hwconf-manager")
from config import get_board_config_path
b = json.load(open(get_board_config_path()))
mods = {}
for f in os.listdir("/usr/share/wb-hwconf-manager/modules"):
    if not f.endswith(".dtso"): continue
    m = re.search(r'compatible-slots\s*=\s*"([^"]+)"',
                  open(f"/usr/share/wb-hwconf-manager/modules/{f}").read())
    if m: mods[f[:-5]] = m.group(1)
for s in b["slots"]:
    fitting = sorted(m for m, c in mods.items() if c in s["compatible"])
    print(f"{s['slot_id']:10s} ({s['id']:14s}) -> {', '.join(fitting) or '(none)'}")
PY
```

`get_board_config_path()` from `wb-hwconf-manager/config.py` resolves the right `boards/<board>.conf` for whatever board you're on — don't hardcode the path. The CLI's `<slot-id>` is the value of the `id` field (e.g. `wb85-mod3`); the persistent-config short form is the `slot_id` field (`mod3`).

## Connector pinout (paste to user when they ask where to wire something)

Top view of the controller PCB. Pin 1 of the UART/I2C/GPIO block is the top-left of that block (3.3 V); odd numbers on the left column, even on the right.

**MOD1..MOD3 on WB6.7–6.9 / WB7.x, MOD1..MOD4 on WB8.x:**

```
       OUT1  ●  ●  OUT2
             ●  ●  OUT3
       ── 1 ─── 2 ──
       3.3V  ●  ●  5V
     TX/SDA  ●  ●  RTS
     RX/SCL  ●  ●  GND
       ═══ UART / I2C / GPIO ═══
```

**MOD4 on WB6.7–6.9 / WB7.x** (extra SPI block instead of OUTs):

```
       ── 1 ── SPI ── 2 ──
       MISO  ●  ●  MOSI
        SCK  ●  ●  CS
       ───────────────────
       3.3V  ●  ●  5V
     TX/SDA  ●  ●  RTS
     RX/SCL  ●  ●  GND
       ═══ UART / I2C / GPIO ═══
```

Pin function depends on the loaded module:

- `wbe2x-generic-uart` → TX (controller out), RX (controller in), RTS.
- `wbe2x-generic-i2c` → TX→SDA, RX→SCL (per `wbe2-i2c.dtsi`; remember external pull-ups, ~4.7 kΩ to 3.3 V).
- GPIO modules → bare digital lines.
- `OUT1..OUT3` are passive contacts on the slot connector — they're routed to the controller's external (front-panel / terminal-block) connector. The installed WBE2 module decides what flows through them (e.g. relay contacts on a `wbe2-do-*` module). When you load `wbe2x-generic-uart` / `-i2c` there's nothing on them from the SoC side.
- `SPI` block (MOD4 on WB6.7–6.9 / WB7.x only) is a separate hardware SPI — wbe2-i-* SPI modules tap it.

**Power rails per module** (from the wiki): `3.3 V` up to **0.5 A**, `5 V` up to **1 A**. Wiki doesn't clarify whether the budget is per slot or shared across all four — assume shared and don't push it.

**Signal lines are 0–3.3 V CMOS without overvoltage protection.** Driving them from 5 V logic damages the controller — use a level shifter for any external 5 V peripheral.

## Verify the switch worked

```bash
ssh root@<HOST> stty -F /dev/ttyMOD3              # OK = pinmux applied; Input/output error = no overlay
ssh root@<HOST> ls -l /dev/i2c-* /dev/ttyMOD*     # check expected device files exist
ssh root@<HOST> cat /sys/class/i2c-adapter/i2c-*/name | grep -i mod   # find which i2c-N is i2c-gpio
ssh root@<HOST> gpioinfo | grep -i "MOD3"         # if "unused input" — pinmux NOT applied
ssh root@<HOST> udevadm info -q all -n /dev/ttyMOD3   # which raw device backs the symlink
ssh root@<HOST> cat /var/lib/wirenboard/hardware.state    # what wb-hwconf-helper thinks is active
```

`gpioinfo` will keep showing `MOD3 TX` / `MOD3 RX` labels regardless of mode — the labels are static. Look at the **third column**: `unused input` means no overlay; an active overlay shows the pin as used by the kernel driver.

## Pitfalls

- **`stty: Input/output error`** on a fresh `/dev/ttyMODx` — pinmux not applied. Run `init` for the slot or check `/etc/wb-hardware.conf`.
- **`wb-mqtt-serial` config has the port with `"enabled": false`** — the daemon does NOT set up pinmux for disabled ports. The port is "released" only in the wb-mqtt-serial sense; the kernel UART is still unmuxed until an overlay loads.
- **`Slot definition file …/slots/mod3.def not found`** on `init` — using short slot-id; needs the board-prefixed form (`wb85-mod3`).
- **`init` errors with a DTS overlay parse error** — the module's `compatible-slots` doesn't match the slot's `compatible` list. Run the capability matrix above to see which slots accept the module. Classic case on wb8.5: `wbe2x-generic-i2c` works on mod3/mod4 but fails on mod1/mod2.
- **`init` succeeds but `gpioinfo` still says `unused input`** — `gpioinfo` only sees pins that the kernel exposed as GPIOs. Pinmuxed pins (UART/I2C/...) leave the GPIO subsystem; the static labels stay. Check `stty` / `/dev/i2c-*` instead.
- **`wbe2x-generic-i2c` is `i2c-gpio` (bit-banged), not hardware I2C.** ~100 kHz max, no clock stretching support beyond what the kernel emulates. For real I2C performance use the SoC's hardware bus (`/dev/i2c-1` etc.) on the side connector instead of MOD.
- **No internal pull-ups on `i2c-gpio`.** Add external pull-ups (4.7 kΩ to 3.3 V typical) on SDA and SCL.
- **Switching modes while a device is connected** can clock garbage during the brief transition between `deinit` and `init`. Power down the peer (or disconnect) before mode-switching if it's stateful.
- **`/etc/wb-hardware.conf = {}`** is normal — defaults from `boards/<board>.conf` apply. The conf file only stores *deviations* from defaults.
- **After `deinit`, `/dev/ttyMODx` symlink stays**, but `stty` fails again. The symlink is created by udev based on the platform UART regardless of pinmux.

## What the agent does NOT do

- **Don't edit `/etc/wb-hardware.conf` for a one-off test.** Use the runtime `init`/`deinit` path so a reboot returns to the board default.
- **Don't replace an active `rs485-1`/`rs485-2` module without checking what's on the bus.** Existing Modbus devices will disconnect.
- **Don't load an arbitrary `.dtso` via `load-overlay` from the internet.** Only ship overlays from `/usr/share/wb-hwconf-manager/modules/` or vetted local files; the kernel device-tree subsystem will happily activate dangerous configs.
- **Don't claim that `init`+`deinit` cycle preserves bus signals.** It doesn't — pins glitch.

## When to ask the user

- The board model is uncertain (no `/sys/firmware/devicetree/base/model` or it doesn't map to a known `boards/*.conf`) — confirm the controller model before guessing the slot-id prefix.
- The target slot is currently `rs485-*` running production Modbus traffic — confirm before `deinit` (will break `wb-mqtt-serial`).
- The new mode requires extra hardware (pull-ups for I2C, isolation, level shifters) — surface that before flipping the mode and finding out the hard way.
- About to write `/etc/wb-hardware.conf` (persistent change) — confirm it should survive a reboot, not just one bench session.

## Documentation

- WB hwconf-manager source: <https://github.com/wirenboard/wb-hwconf-manager>
- WB extension modules + pinouts + power specs (canonical): <https://wiki.wirenboard.com/wiki/Wiren_Board:_Extension_Modules>
- Linux `i2c-gpio` binding: kernel `Documentation/devicetree/bindings/i2c/i2c-gpio.yaml`
- Sister skill: `wb-serial` (Modbus/RTU on the default RS-485 mode).
