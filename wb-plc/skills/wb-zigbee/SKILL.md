---
name: wb-zigbee
description: Zigbee devices on WB via zigbee2mqtt — bridge/state liveness probe, native vs Docker install detection, wb-mqtt-zigbee vs wb-zigbee2mqtt converter recognition, IEEE-address (0x...) and zigbee_<id> topic patterns, pairing, control, OTA.
allowed-tools: Bash Read WebFetch
---

# zigbee

## CRITICAL RULES

> **NEVER call `wb-cli` without `--json` from an agent.**
> Human-mode output is unparseable; always use:
> `wb-cli --json <command>`
> This applies to every call including help: `wb-cli --json <group> --help`.

**`<HOST>` variable:** in all examples below `<HOST>` means `wirenboard-<SN>.local`, where `<SN>` is the serial number (e.g. `wirenboard-AABBCCDD.local`). Substitute the real address.

Zigbee devices on a Wiren Board controller via zigbee2mqtt.

## Architecture

**zigbee2mqtt** talks to the Zigbee adapter via `/dev/ttyMOD<N>` and publishes to `zigbee2mqtt/<friendly_name>`. It can run **either natively** (`systemctl is-active zigbee2mqtt`) **or in Docker** (`docker ps | grep zigbee`) — both cases occur. The install method is **not determined by `systemctl`** — it always shows `inactive` for a containerized install even when the bridge is working.

WB converters turn Z2M devices into native WB MQTT (`/devices/...`) so wb-rules and the web UI can see them:

| Converter | Topic prefix | Notes |
|-----------|---------------|-------------|
| **wb-mqtt-zigbee** (new) | `/devices/zigbee_*/controls/*` | Bidirectional controls, support via `/on` |
| **wb-zigbee2mqtt** (old, `1.x`) | `/devices/0x<ieee>/controls/*` (topic name = full IEEE address) | Read-only bridge, control via `wb-cli mqtt write zigbee2mqtt/<friendly>/set` |

Which one is installed — determine via `dpkg -l | grep -E 'wb-(mqtt-zigbee|zigbee2mqtt)'` and check device names on the bus:
```bash
ssh root@<HOST> wb-cli --json mqtt list '/devices/+/meta/name'
```
In the output: `0x...` = old converter (`wb-zigbee2mqtt`), `zigbee_<id>` = new converter (`wb-mqtt-zigbee`).

## How to identify

Signs:
- MQTT has devices with names like `0x00158d...`, `0x00124b...`, `0x04cd15...`, `0xd44867...` — those are IEEE addresses (Zigbee).
- In `/devices/...` both formats may be present: `/devices/0x<ieee>` (old converter) or `/devices/zigbee_<id>` (new).
- Topics `zigbee2mqtt/bridge/state`, `zigbee2mqtt/bridge/devices`, `zigbee2mqtt/bridge/info` — published by Z2M itself, independently of the WB converter.

## Bridge probe

**The true liveness check is `bridge/state`, not `systemctl`:**

```bash
ssh root@<HOST> wb-cli --json mqtt read 'zigbee2mqtt/bridge/state'
```

Expected: `{"state":"online"}` (or just `online` on older versions). If empty/timeout — the bridge is dead or there's no MQTT connectivity.

Only if `bridge/state` is empty, find out **where** Z2M actually lives:

```bash
ssh root@<HOST> 'systemctl is-active zigbee2mqtt 2>&1; docker ps --format "{{.Names}} {{.Status}}" 2>/dev/null | grep -i zigbee'
```

One of the two (or both) will answer. Then — `journalctl -u zigbee2mqtt -n 50` or `docker logs --tail 50 zigbee2mqtt`.

## Information about the bridge and devices

`bridge/devices` is a large JSON (tens of KB). Don't try `head -c 200` — that gives broken JSON that can't be parsed. Write it whole right away:

```bash
ssh root@<HOST> wb-cli --json mqtt read 'zigbee2mqtt/bridge/devices' | jq -r '.data.payload' > /tmp/z2m-devices.json
ssh root@<HOST> wb-cli --json mqtt read 'zigbee2mqtt/bridge/info'    | jq -r '.data.payload' > /tmp/z2m-info.json
```

**Parsing — via jq** (available on all current WB firmwares):

```bash
# Device list: friendly_name | ieee | model | vendor
jq -r '.[] | select(.type != "Coordinator") | [.friendly_name, .ieee_address, .definition.model // "?", .definition.vendor // "?"] | @tsv' /tmp/z2m-devices.json
```

If `jq` isn't there (minimal image or very old release) — `python3 -c '...'` as a fallback. Don't nest python in a single SSH call with f-strings: quote crossing is fragile. Easier to copy the `.json` locally and parse on the host.

`bridge/info` contains: `version` (Z2M), `coordinator.type` (adapter: ZStack3x0, EmberZNet, etc.), `permit_join` (bool, should be `false` in idle state), `restart_required`, `config.availability.enabled`.

**`last_seen` per-device** — published in `bridge/devices` **only if** `availability.enabled: true` is set in `configuration.yaml`. Disabled by default — absence of the field **doesn't mean** the device is offline.

## Current device values

### Via wb-cli (preferred for WB-converted devices)

```bash
# New wb-mqtt-zigbee converter:
ssh root@<HOST> wb-cli --json dev zigbee_<id>
# Old wb-zigbee2mqtt converter:
ssh root@<HOST> 'wb-cli --json dev "0x<ieee>"'
```

Returns all controls with current values, types, and error flags in JSON.

### Via raw MQTT (Z2M-native data only — no WB converter)

```bash
# Current values via Z2M (raw JSON with all exposures, for devices without WB converter):
ssh root@<HOST> wb-cli --json mqtt read 'zigbee2mqtt/<friendly_name>'
```

## Controlling a device

**Via wb-cli (if `wb-mqtt-zigbee` converter is present):**
```bash
ssh root@<HOST> wb-cli --json dev zigbee_<id>/<channel> <value>
```

**Via raw MQTT (WB converter):**
```bash
ssh root@<HOST> "wb-cli --json mqtt write '/devices/zigbee_<id>/controls/<channel>/on' '<value>'"
```

**Via Z2M directly (always works, even without WB converter):**
```bash
ssh root@<HOST> "wb-cli --json mqtt write 'zigbee2mqtt/<friendly_name>/set' '{\"state\":\"ON\"}'"
```

## Pairing

⚠️ **This changes bridge state.** Coordinate with the user before pairing — after `permit_join: true` any Zigbee device in range can join without authorization.

Enable pairing mode for 4 minutes:
```bash
ssh root@<HOST> "wb-cli --json mqtt write 'zigbee2mqtt/bridge/request/permit_join' '{\"value\": true, \"time\": 240}'"
```

Hold the pair button on the device. After pairing **must disable**:
```bash
ssh root@<HOST> "wb-cli --json mqtt write 'zigbee2mqtt/bridge/request/permit_join' '{\"value\": false}'"
```

Verify it's disabled:
```bash
ssh root@<HOST> wb-cli --json mqtt read 'zigbee2mqtt/bridge/info' | jq -r '.data.payload | fromjson | .permit_join'
# should be false
```

## Pitfalls

- `systemctl is-active zigbee2mqtt` ≠ bridge probe. If Z2M is in Docker, the answer is always `inactive`. Use `bridge/state`.
- `wb-cli mqtt list 'zigbee2mqtt/#'` — megabytes of data (full retained history). Don't.
- `head -c 200` for `bridge/devices` — gives broken JSON, doesn't parse.
- Absence of `last_seen` ≠ device offline. Check `bridge/info → config.availability.enabled`.
- `bridge/request/permit_join` without user confirmation — destructive.
- LQI < 80 + voltage < 2900 mV — battery is about to die, even if `battery: 100%` (CR2032 reports 100% until the very end, then drops sharply).
- WBE2R-R-ZIGBEE modules and similar aren't visible on the web UI "Devices" page — that's normal, they're on the Z2M side.

## What the agent does NOT do

- **Run `bridge/request/permit_join` without user confirmation.** Pairing mode lets ANY nearby Zigbee device join — security boundary.
- **Forget to disable `permit_join` after pairing.** If the agent moves on, the network stays open. Always re-check `bridge/info → permit_join == false`.
- **`wb-cli mqtt list 'zigbee2mqtt/#'`** — pulls megabytes of retained history.
- **Pipe `bridge/devices` through `head -c 200`** — breaks the JSON. Parse cleanly with `jq -r '.payload | fromjson'`.
- **Use `systemctl is-active zigbee2mqtt`** to decide if the bridge is alive — Docker installs always show `inactive`. Use the retained `bridge/state` topic instead.
- **Assume battery is fine because `battery: 100%`.** CR2032 reports 100% until it falls off a cliff — also read LQI < 80 and voltage < 2900 mV as warning signals.

## When to ask the user

- About to pair a new device on a production controller — confirm timing (240-sec open window) and which device exactly.
- Removing a device from the network — confirm; some devices need manual factory-reset afterwards.
- Initiating OTA on a live device — confirm; lights / switches may flicker or restart during firmware update.
- The bridge JSON shows a device the user doesn't recognize — surface it (rogue device may have joined during a previous `permit_join` window).
- About to switch the WB-Zigbee converter (wb-zigbee2mqtt 1.x → wb-mqtt-zigbee) — confirm; topic structure changes and existing wb-rules break.

## Documentation

- <https://wiki.wirenboard.com/wiki/Zigbee>
- <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>
- <https://wiki.wirenboard.com/wiki/WBE2R-R-ZIGBEE_v.2_ZigBee_Extension_Module>
