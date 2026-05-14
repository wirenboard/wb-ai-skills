# Verbose PUBLISH tracing — `wb-cli mqtt-debug`

To find **which MQTT client** publishes to a given topic (wb-rules, web UI, an external client, a misbehaving driver), use the dedicated plugin instead of editing `/etc/mosquitto/conf.d/` by hand. **Always quote topics — WB control names commonly contain spaces** (e.g. `Channel 1 Dimming Level`), and over SSH wrap the whole command in double quotes so the controller shell sees the spaces.

> The `client_id` column / field is the **literal MQTT identifier** the publisher chose at CONNECT time, as reported by mosquitto after `Received PUBLISH from`. It's not a systemd unit name and not always equal to the package name — see the table below.

## Capture examples

```bash
# Short ad-hoc capture — single substring filter (grep-style)
ssh root@<HOST> "wb-cli --json mqtt-debug capture --seconds 60 \
    --topic '/devices/wb-mr6c_7/controls/K1' --client-id wb-rules"

# Multiple --topic / --client-id values OR together
ssh root@<HOST> "wb-cli --json mqtt-debug capture --seconds 60 \
    --topic 'wb-mr6c_2/controls/K1' --topic 'wb-mr6c_2/controls/K2' \
    --client-id wb-rules --client-id wb-mqtt-homeui"

# MQTT-style wildcards: + matches one level, # matches all remaining levels
ssh root@<HOST> "wb-cli --json mqtt-debug capture --seconds 60 \
    --topic '/devices/+/controls/Channel 1 Dimming Level/on'"
ssh root@<HOST> "wb-cli --json mqtt-debug capture --seconds 60 \
    --topic '/devices/wb-mr6c_2/#'"

# Toggle persistently (verbose logging stays on after capture)
ssh root@<HOST> wb-cli mqtt-debug enable
ssh root@<HOST> wb-cli mqtt-debug status
ssh root@<HOST> wb-cli mqtt-debug disable

# Long capture (hours / days) — runs as a wb-cli job, JSON envelope on disk
ssh root@<HOST> "wb-cli --json mqtt-debug capture --seconds 86400 --background \
    --output /mnt/data/ai/wb-cli/mqtt-debug-\$(date +%s).json"
# poll the job:
ssh root@<HOST> wb-cli --json job wait <unit>
ssh root@<HOST> "jq '.data.entries[] | select(.client_id != \"wb-adc\")' \
    /mnt/data/ai/wb-cli/mqtt-debug-<TS>.json"
```

The plugin writes the same drop-in (`/etc/mosquitto/conf.d/debug-verbose.conf` with `log_type all`) that you would put there manually, restarts `mosquitto`, parses every `Received PUBLISH …` line out of the journal into structured records:

```json
{"timestamp": "2026-05-13T09:44:31+00:00",
 "client_id": "system__wb-rules__cAbCdEfGhIjK",
 "topic": "/devices/wb-mr6c_7/controls/K1/on",
 "qos": 0, "retain": false, "dup": false,
 "message_id": 1234, "payload_size": 1}
```

After an inline capture the previous on/off state is restored automatically (try/finally). For long captures, `--background` writes the JSON to `--output` and the plugin still restores the previous state when the job finishes. To leave verbose logging on after a capture, pass `--keep-enabled`.

## Common `client_id` values to expect

| `client_id` mosquitto reports | who that is |
|---|---|
| `wb-modbus` | `wb-mqtt-serial` (legacy client_id, kept for back-compat) |
| `system__wb-rules__<hex>` | a wb-rules engine instance |
| `wb-mqtt-homeui-<hex>` | the web UI |
| `wb-mqtt-knx`, `wb-zigbee2mqtt`, `wb-w1` | corresponding drivers — each picks a sensible client_id |
| `wb-cli-<pid>` | `wb-cli mqtt write` (since 1.5.2) |
| `mosquitto_pub-<pid>` | `mosquitto_pub` invoked with `-i` set automatically |
| `auto-<UUID>` | a client that connected with an **empty** client_id — mosquitto ≥2.0 auto-generates a UUID. Cannot be tied to a specific process |
| `tasmota_*`, `shellyplus_*` | external IoT clients |

If you see `auto-<UUID>` for your own ad-hoc publishes, pass `-i some-name` to `mosquitto_pub` to make them identifiable in the capture.
