---
name: wb-zigbee
description: Zigbee devices on WB via MCP — discovery, pairing, control via zigbee2mqtt.
allowed-tools: Bash Read WebFetch
---

# zigbee (MCP)

Zigbee devices on a Wiren Board controller via zigbee2mqtt. Control and state go through MQTT — use `wb_mqtt_*` tools.

## Architecture

**zigbee2mqtt** talks to the Zigbee adapter via `/dev/ttyMOD<N>` and publishes to `zigbee2mqtt/<friendly_name>`. It can be running **either natively** (via systemd) **or in Docker** — both are seen in the wild. `wb_failed` for a Docker installation will show nothing even when the bridge is working.

WB converters expose Z2M devices as native WB-MQTT (`/devices/...`) so wb-rules and Web UI can see them:

| Converter | Topic prefix | Notes |
|-----------|--------------|-------|
| **wb-mqtt-zigbee** (new) | `/devices/zigbee_*/controls/*` | Two-way controls, support via `/on` |
| **wb-zigbee2mqtt** (old, `1.x`) | `/devices/0x<ieee>/controls/*` (topic name = full IEEE address) | Read-only bridge, control via `zigbee2mqtt/<friendly>/set` |

Which one is installed — `wb_ssh_exec` `dpkg -l | grep -E "wb-(mqtt-zigbee\|zigbee2mqtt)"` and `wb_mqtt_devices` (look for `0x...` or `zigbee_...` names).

## How to recognize

- IEEE addresses `0x00158d...`, `0x00124b...`, `0x04cd15...`, `0xd44867...` in `wb_mqtt_devices` — these are Zigbee.
- In `/devices/...` both formats can appear: `0x<ieee>` (old converter) or `zigbee_<id>` (new) — DON'T assume in advance.
- Topics `zigbee2mqtt/bridge/state`, `bridge/devices`, `bridge/info` — published by Z2M itself, format doesn't depend on the converter.

## Tool routing

| Intent | Tool |
|--------|------|
| Probe the bridge (correct path) | `wb_mqtt_read topic=zigbee2mqtt/bridge/state` |
| Z2M in Docker / native — where it lives | `wb_ssh_exec` `systemctl is-active zigbee2mqtt 2>&1; docker ps --format "{{.Names}}" 2>/dev/null \| grep -i zigbee` |
| Bridge info (version, coordinator, permit_join) | `wb_mqtt_read topic=zigbee2mqtt/bridge/info` |
| Paired devices (raw JSON, may be >20 KB) | `wb_mqtt_read topic=zigbee2mqtt/bridge/devices` |
| Enable/disable permit_join (⚠️ destructive) | `wb_mqtt_write topic=zigbee2mqtt/bridge/request/permit_join` |
| Read device state (raw Z2M) | `wb_mqtt_read topic=zigbee2mqtt/<friendly_name>` |
| Read via WB converter | `wb_mqtt_controls device=zigbee_<id>` or `wb_mqtt_controls device=0x<ieee>` |
| Control via WB converter | `wb_mqtt_write topic=/devices/zigbee_<id>/controls/<c>/on` |
| Control via Z2M directly | `wb_mqtt_write topic=zigbee2mqtt/<friendly_name>/set value='{"state":"ON"}'` |
| Z2M logs (native) | `wb_logs unit=zigbee2mqtt` |
| Z2M logs (container) | `wb_ssh_exec` `docker logs --tail 50 zigbee2mqtt` |

## Probe the bridge — correct way

**`wb_failed` is not suitable for probing Z2M in Docker.** Use `wb_mqtt_read zigbee2mqtt/bridge/state` — it works regardless of installation method.

```
wb_mqtt_read sn=<SN> topic=zigbee2mqtt/bridge/state
```

Expected: `{"state":"online"}` (or `online` in older versions). Empty/timeout — the bridge is dead or no MQTT connection.

If empty — figure out **where** Z2M lives:
- `wb_ssh_exec` `systemctl is-active zigbee2mqtt 2>&1` (`active` → native) **or**
- `wb_ssh_exec` `docker ps --format "{{.Names}} {{.Status}}" \| grep -i zigbee` (`Up ...` → container).

Logs: `wb_logs unit=zigbee2mqtt` (for native) or `wb_ssh_exec` `docker logs --tail 50 zigbee2mqtt` (for container).

## Bridge info

```
wb_mqtt_read sn=<SN> topic=zigbee2mqtt/bridge/info
```

Contains: `version` (Z2M), `coordinator.type` (adapter: ZStack3x0, EmberZNet, etc.), `permit_join` (must be `false` in steady state), `restart_required`, `config.availability.enabled`.

**Per-device `last_seen`** in `bridge/devices` is published only if `availability.enabled: true` is set in `configuration.yaml`. Disabled by default — absence of the field **does not mean** the device is offline.

## Pairing

⚠️ **Destructive** — after `permit_join: true` any Zigbee device within range can join. Coordinate with the user.

```
wb_mqtt_write sn=<SN> topic=zigbee2mqtt/bridge/request/permit_join value='{"value": true, "time": 240}'
```

After pairing, be sure to disable:

```
wb_mqtt_write sn=<SN> topic=zigbee2mqtt/bridge/request/permit_join value='{"value": false}'
```

Confirm:
```
wb_mqtt_read sn=<SN> topic=zigbee2mqtt/bridge/info
# in the response permit_join must be false
```

After successful pairing — `wb_mqtt_devices` will show the new IEEE/friendly_name.

## Gotchas

- `wb_failed` ≠ bridge probe for Docker-Z2M.
- `wb_mqtt_list prefix=zigbee2mqtt/` without limits can return the whole Z2M history (dozens of topics). Better to point-target via `wb_mqtt_read`.
- `bridge/devices` is a large JSON. Truncation (`head -c 200` etc.) is pointless, parse only as a whole.
- Absence of `last_seen` ≠ device offline. Check `bridge/info → config.availability.enabled`.
- LQI < 80 + voltage < 2900 mV — battery will die soon, even with `battery: 100%` (CR2032 reports 100% to the very end).
- The WBE2R-R-ZIGBEE module isn't visible on the "Devices" page in Web UI — that's normal, it's on the Z2M side.

**Z2M installation** — `/wb-software-install` (native from WB repo, **not** Docker — bound to the adapter).

## Documentation

- <https://wiki.wirenboard.com/wiki/Zigbee>
- <https://wiki.wirenboard.com/wiki/Zigbee2MQTT>
- <https://wiki.wirenboard.com/wiki/WBE2R-R-ZIGBEE_v.2_ZigBee_Extension_Module>
