---
name: wb-mqtt-broker
description: mosquitto administration on a Wiren Board controller via MCP — listeners, users, ACLs, bridges to external brokers, TLS.
allowed-tools: Bash Read Write WebFetch
---

# mqtt-broker (MCP)

`mosquitto` via MCP tools. Managed by configs in `/etc/mosquitto/conf.d/*.conf` (do NOT edit the main `mosquitto.conf`).

Load this when: "expose MQTT externally", "need passwords on MQTT", "configure TLS", "bridge to cloud", "bridge to HA", "can't connect to MQTT from laptop", "mosquitto", "ACL for MQTT".

## Tool routing

| Intent | Tool |
|--------|------|
| Broker status | `wb_systemd_unit unit=mosquitto` |
| Broker logs | `wb_logs unit=mosquitto since="10m ago"` |
| Config check without restart | `wb_ssh_exec` `mosquitto -c /etc/mosquitto/mosquitto.conf -t` |
| Create/update password | `wb_ssh_exec` `mosquitto_passwd [-c] /etc/mosquitto/passwd/default.conf <user>` |
| Write listener config | `wb_write_file path=/etc/mosquitto/conf.d/10listeners.conf` |
| Write ACL | `wb_write_file path=/etc/mosquitto/acl/default.conf` |
| Write bridge | `wb_write_file path=/etc/mosquitto/conf.d/20bridges.conf` |
| Reload (passwd/acl without restart) | `wb_systemd_unit unit=mosquitto action=reload` |
| Restart (listener/bridge/TLS changes) | `wb_systemd_unit unit=mosquitto action=restart` |
| $SYS statistics | `wb_mqtt_list prefix='$SYS/broker/+' timeout=2` |

## Architecture

```
/etc/mosquitto/mosquitto.conf            # includes 3 directories in order:
  /usr/share/wb-configs/mosquitto/        # WB defaults — DO NOT touch
  /etc/mosquitto/conf.d/                  # user — yours
  /usr/share/wb-configs/mosquitto-post/   # WB post — DO NOT touch

/etc/mosquitto/conf.d/
├── 00default_listener.conf   # Unix socket for WB services (DO NOT touch)
├── 10listeners.conf          # port 1883 / 8883 — edits here
└── 20bridges.conf            # bridges — here
```

WB services talk via the Unix socket (anonymous). External clients — via 1883/8883, do auth **there**.

## Scenario: lock the broker with a password

1. Create the password file:
   ```
   wb_ssh_exec sn=<SN> cmd='mkdir -p /etc/mosquitto/passwd; chown mosquitto:mosquitto /etc/mosquitto/passwd'
   wb_ssh_exec sn=<SN> cmd='mosquitto_passwd -c /etc/mosquitto/passwd/default.conf <user>'
   wb_ssh_exec sn=<SN> cmd='chown mosquitto:mosquitto /etc/mosquitto/passwd/default.conf; chmod 0640 /etc/mosquitto/passwd/default.conf'
   ```
2. Listener config with auth:
   ```
   wb_write_file sn=<SN> path=/etc/mosquitto/conf.d/10listeners.conf content='listener 1883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf'
   ```
3. ACL (minimum — deny anonymous):
   ```
   wb_write_file sn=<SN> path=/etc/mosquitto/acl/default.conf content='topic deny #
user <user>
topic readwrite #'
   ```
4. Restart:
   ```
   wb_systemd_unit sn=<SN> unit=mosquitto action=restart
   ```
5. Test:
   ```
   wb_ssh_exec sn=<SN> cmd="mosquitto_sub -h localhost -p 1883 -u <user> -P <pwd> -t '/devices/+/meta/name' -C 3 -W 3"
   ```

## Scenario: bridge to Home Assistant

```
wb_write_file sn=<SN> path=/etc/mosquitto/conf.d/20bridges.conf content='connection ha-bridge
address ha.local:1883
topic /devices/# out 0 wb/<SN>/
topic ha/wb/cmd/+ in 0
remote_username <ha_user>
remote_password <ha_pwd>
keepalive_interval 60
notifications true
notifications_topic wb/<SN>/bridge/state
cleansession false'
wb_systemd_unit sn=<SN> unit=mosquitto action=restart
wb_mqtt_read sn=<SN> topic=wb/<SN>/bridge/state
```

`wb/<SN>/bridge/state` = `online` — the bridge is up.

## Scenario: TLS on 8883

Self-signed CA + server cert (see bash-flavor twin for openssl commands) → `wb_ssh_exec` creates `/etc/mosquitto/certs/{ca.crt, server.crt, server.key}`. Then extend the listener:

```
listener 8883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf
cafile /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile /etc/mosquitto/certs/server.key
```

## When to reload, when to restart

- **`reload`** — `password_file`, `acl_file` (new users/rules without downtime).
- **`restart`** — `listener`, `bridge`, TLS, structural config changes. ≈1 sec downtime; internal WB services via Unix socket survive it.

## Gotchas

- **`per_listener_settings false`** — disabling allows anonymous to all, including 1883. WB sets `true` in `00default_listener.conf` — don't reset it.
- **Editing `mosquitto.conf` directly** — everything in `conf.d/`. The base is overwritten by updates.
- **Closed 1883, forgot about WB services** — they use Unix socket, unaffected. But if you broke `per_listener_settings`, they'll lose connection.
- **mosquitto_passwd without `-c` for a new file** — the password won't save. With `-c` — wipes existing. First time — `-c`, then without.
- **ACL without `topic deny #`** — anonymous (if allowed) gets full readwrite.
- **Bridge without `cleansession false`** — message loss on disconnect.
- **password_file rights** — `mosquitto:mosquitto 0640`. Otherwise `Unable to open password file ... Permission denied`.

## Related skills

- `/wb-network` — if external client can't connect, check firewall.
- `/wb-cloud` — official wirenboard.cloud bridge is a separate agent, not a mosquitto bridge.
- `/wb-services` — override-conf for mosquitto.

Details (TLS certificates, ACL syntax, bridge format) — bash-flavor twin `/wb-mqtt-broker`.

## Documentation

- mosquitto.conf: <https://mosquitto.org/man/mosquitto-conf-5.html>
- mosquitto_passwd: <https://mosquitto.org/man/mosquitto_passwd-1.html>
- Bridges: <https://mosquitto.org/documentation/bridges/>
