# MQTT conventions and MQTT-RPC

Full spec: <https://github.com/wirenboard/conventions/blob/main/README.md>

## Topic structure

```
/devices/<device-id>/meta                    — device metadata (JSON, retained)
/devices/<device-id>/meta/error              — device error state / LWT (non-null = error)
/devices/<device-id>/controls/<ctrl-id>      — current control value (retained)
/devices/<device-id>/controls/<ctrl-id>/on   — write target here to set the value
/devices/<device-id>/controls/<ctrl-id>/meta — control metadata (JSON, retained)
```

## Naming (2024+ rules)

- Lowercase, words separated by underscores, no punctuation/special chars
- Device topic: max 4 words + numbers
- Good: `/devices/room_light/meta`
- Bad: `/devices/Room-Light#1/meta`

## Device `/meta` JSON

```json
{
  "driver": "my-driver",
  "title": { "en": "Room Light", "ru": "Освещение комнаты" }
}
```

## Control `/meta` JSON

```jsonc
{
  "type": "switch",           // required — see types below
  "units": "W",              // for type=value only
  "min": 0, "max": 100,
  "precision": 0.1,
  "order": 1,
  "readonly": false,
  "hidden": false,
  "title": { "en": "Lamp", "ru": "Лампа" }
}
```

## Control types

| Type | `meta/type` | Values |
|---|---|---|
| Switch (toggle) | `switch` | `0` / `1` |
| Alarm indicator | `alarm` | `0` / `1` |
| Push button (stateless) | `pushbutton` | `1` (no retained) |
| Range slider | `range` | integer in [min, max] |
| Generic float value | `value` | float, use `units` field |
| Text | `text` | any string |
| RGB color | `rgb` | `"R;G;B"` (0–255 each) |
| Unix timestamp | `unixtime` | integer |

Specific typed controls (`temperature`, `voltage`, etc.) are **deprecated** — use `type: value` + `units` instead.

## Publishing rules

- All `/meta` topics: published with **retained** flag on driver startup
- `/devices/<id>/meta/error` used as **LWT** (Last Will and Testament) — set to non-empty value on connect
- Each device must be published by a **single driver**; no two drivers share the same device ID

## Subscribing

```bash
# Monitor all controls live
mosquitto_sub -t '/devices/+/controls/+' -v

# Write to a control
mosquitto_pub -t '/devices/room_light/controls/lamp/on' -m '1'
```

## MQTT-RPC

Full spec: <https://github.com/wirenboard/mqtt-rpc>

### Topic pattern

```
/rpc/v1/<driver>/<service>/<method>/<client_id>        — send request here
/rpc/v1/<driver>/<service>/<method>/<client_id>/reply  — receive response here
```

`client_id`: unique per request — use UUID v4 or MQTT client ID.

### Request format

```json
{ "id": "1234", "params": { "A": 1, "B": 2 } }
```

`id`: decimal string representation of uint64.

### Success response

```json
{ "id": "1234", "result": 42, "error": null }
```

### Error response

```json
{ "id": "1234", "error": { "message": "divide by zero", "code": -1, "data": "ErrorType" } }
```

**Rules:** strict JSON — no comments, no `Inf`/`NaN` values, all keys in quotes.

### Discover RPC services on a controller

```bash
ssh root@<HOST> wb-cli --json mqtt sub '/rpc/v1/+/+/+'
```

### Python reference implementation

<https://github.com/wirenboard/python-mqtt-rpc>
