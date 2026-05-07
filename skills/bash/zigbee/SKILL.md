---
name: zigbee
description: Zigbee devices on WB — discovery, pairing, control via zigbee2mqtt.
allowed-tools: Bash Read WebFetch
---

# zigbee

Zigbee devices on a Wiren Board controller via zigbee2mqtt.

## Architecture

**zigbee2mqtt** talks to the Zigbee adapter via `/dev/ttyMOD<N>` and publishes to `zigbee2mqtt/<friendly_name>`. It can run **either natively** (`systemctl is-active zigbee2mqtt`) **or in Docker** (`docker ps | grep zigbee`) — both cases occur. The install method is **not determined by `systemctl`** — it'll definitively show `inactive` for a containerized install even when the bridge is working.

WB converters turn Z2M devices into native WB MQTT (`/devices/...`) so wb-rules and the web UI can see them:

| Converter | Topic prefix | Notes |
|-----------|---------------|-------------|
| **wb-mqtt-zigbee** (new) | `/devices/zigbee_*/controls/*` | Bidirectional controls, support via `/on` |
| **wb-zigbee2mqtt** (old, `1.x`) | `/devices/0x<ieee>/controls/*` (topic name = full IEEE address) | Read-only bridge, control via `mosquitto_pub zigbee2mqtt/<friendly>/set` |

Which one is installed — determine via `dpkg -l | grep -E 'wb-(mqtt-zigbee\|zigbee2mqtt)'` and `mosquitto_sub /devices/+/meta/name -C 50 -W 3` (look for `0x...` names or `zigbee_<id>`).

## How to identify

Signs:
- MQTT has devices with names like `0x00158d...`, `0x00124b...`, `0x04cd15...`, `0xd44867...` — those are IEEE addresses (Zigbee).
- In `/devices/...` both formats may be present: `/devices/0x<ieee>` (old converter) or `/devices/zigbee_<id>` (new).
- Topics `zigbee2mqtt/bridge/state`, `zigbee2mqtt/bridge/devices`, `zigbee2mqtt/bridge/info` — published by Z2M itself, independently of the WB converter.

## Bridge probe

**The true liveness check is `bridge/state`, not `systemctl`:**

```bash
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/state' -C 1 -W 5"
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
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/devices' -C 1 -W 5" > /tmp/z2m-devices.json
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/info'    -C 1 -W 5" > /tmp/z2m-info.json
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

```bash
# Current values via Z2M (raw):
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/<friendly_name>' -C 1 -W 5"

# Via WB converter (depends on which is installed):
# New wb-mqtt-zigbee:
ssh root@<HOST> "mosquitto_sub -t '/devices/zigbee_<id>/controls/+' -C 50 -W 3"
# Old wb-zigbee2mqtt:
ssh root@<HOST> "mosquitto_sub -t '/devices/0x<ieee>/controls/+' -C 50 -W 3"
```

## Controlling a device

**Write via WB converter (if `wb-mqtt-zigbee` is present):**
```bash
ssh root@<HOST> "mosquitto_pub -t '/devices/zigbee_<id>/controls/<channel>/on' -m '<value>'"
```

**Via Z2M directly (always works):**
```bash
ssh root@<HOST> "mosquitto_pub -t 'zigbee2mqtt/<friendly_name>/set' -m '{\"state\":\"ON\"}'"
```

## Pairing

⚠️ **This changes bridge state.** Coordinate with the user before pairing — after `permit_join: true` any Zigbee device in range can join without authorization.

Enable pairing mode for 4 minutes:
```bash
ssh root@<HOST> "mosquitto_pub -t 'zigbee2mqtt/bridge/request/permit_join' -m '{\"value\": true, \"time\": 240}'"
```

Hold the pair button on the device. After pairing **must disable**:
```bash
ssh root@<HOST> "mosquitto_pub -t 'zigbee2mqtt/bridge/request/permit_join' -m '{\"value\": false}'"
```

Verify it's disabled:
```bash
ssh root@<HOST> "mosquitto_sub -t 'zigbee2mqtt/bridge/info' -C 1 -W 5" | jq '.permit_join'
# should be false
```

## Pitfalls

- `systemctl is-active zigbee2mqtt` ≠ bridge probe. If Z2M is in Docker, the answer is always `inactive`. Use `bridge/state`.
- `mosquitto_sub -t 'zigbee2mqtt/#'` — megabytes of data (full retained history). Don't.
- `head -c 200` for `bridge/devices` — gives broken JSON, doesn't parse.
- Absence of `last_seen` ≠ device offline. Check `bridge/info → config.availability.enabled`.
- `bridge/request/permit_join` without user confirmation — destructive.
- LQI < 80 + voltage < 2900 mV — battery is about to die, even if `battery: 100%` (CR2032 reports 100% until the very end, then drops sharply).
- WBE2R-R-ZIGBEE modules and similar aren't visible on the web UI "Devices" page — that's normal, they're on the Z2M side.

## Documentation

- <https://wiki.wirenboard.com/wiki/Zigbee>
- <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>
- <https://wiki.wirenboard.com/wiki/WBE2R-R-ZIGBEE_v.2_ZigBee_Extension_Module>
