---
name: wb-mqtt-broker
description: Administering mosquitto on a Wiren Board controller — listeners, users, ACLs, bridges to external brokers, TLS. /etc/mosquitto/conf.d/.
allowed-tools: Bash Read Write WebFetch
---

# mqtt-broker

`mosquitto` on a WB controller is the main MQTT broker through which all WB services and user applications communicate. Managed via `/etc/mosquitto/conf.d/*.conf` (DON'T edit `mosquitto.conf` directly).

Load this on: "open MQTT externally", "MQTT needs passwords", "set up TLS", "bridge to cloud", "bridge to HA", "can't connect to MQTT from laptop", "mosquitto", "ACL for MQTT", "passwords on the broker", "encrypt MQTT".

## Config structure

```
/etc/mosquitto/mosquitto.conf            # includes 3 directories in order:
  /usr/share/wb-configs/mosquitto/        # WB defaults (DON'T touch)
  /etc/mosquitto/conf.d/                  # user — write here
  /usr/share/wb-configs/mosquitto-post/   # WB post (DON'T touch)

/etc/mosquitto/conf.d/
├── 00default_listener.conf   # Unix socket for wb services (DON'T touch)
├── 10listeners.conf          # external listeners (port 1883, 8883) — yours
├── 20bridges.conf            # bridges to other brokers — yours
└── 21bridge.conf.example     # bridge template

/etc/mosquitto/passwd/        # password files (mosquitto_passwd -c)
/etc/mosquitto/acl/           # ACL files (topics per-user)
/etc/mosquitto/certs/         # TLS certificates (you'll create)
```

**Principle**: WB services talk via the Unix socket `/var/run/mosquitto/mosquitto.sock` (anonymously — 00default_listener). External clients — via 1883/8883, and that's where you do authentication.

By default (factory): listener 1883 anonymous = broker open to the world. **For production this needs to be closed.**

## Basic commands

```bash
ssh root@<HOST> 'systemctl is-active mosquitto'
ssh root@<HOST> 'mosquitto -c /etc/mosquitto/mosquitto.conf -t'      # config check without starting
ssh root@<HOST> 'journalctl -u mosquitto -n 50 --no-pager'
ssh root@<HOST> "mosquitto_sub -h localhost -t '\$SYS/#' -C 5"        # broker system stats
ssh root@<HOST> "mosquitto_sub -h localhost -t '\$SYS/broker/clients/connected' -C 1"
```

## Authentication: passwords

### Create password file

```bash
ssh root@<HOST> 'mkdir -p /etc/mosquitto/passwd; chown mosquitto:mosquitto /etc/mosquitto/passwd'
ssh root@<HOST> 'mosquitto_passwd -c /etc/mosquitto/passwd/default.conf <username>'
# enter password: ****
ssh root@<HOST> 'chown mosquitto:mosquitto /etc/mosquitto/passwd/default.conf; chmod 0640 /etc/mosquitto/passwd/default.conf'
```

`-c` — create file (overwrites existing!). Without `-c` — add a user to an existing file. Delete user: `mosquitto_passwd -D /etc/mosquitto/passwd/default.conf <username>`.

### Configure listener to use passwords

In `/etc/mosquitto/conf.d/10listeners.conf` there's already an example. Edit to disable anonymous:

```bash
ssh root@<HOST> 'cat > /etc/mosquitto/conf.d/10listeners.conf' <<'EOF'
listener 1883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf
EOF
ssh root@<HOST> 'systemctl restart mosquitto'
```

`per_listener_settings true` (in `00default_listener.conf`) is key: allows different `allow_anonymous` for different listeners. The internal socket stays anonymous, the external one requires a password.

### Test

```bash
ssh root@<HOST> "mosquitto_sub -h localhost -p 1883 -u <user> -P <pwd> -t '/devices/+/meta/name' -C 3 -W 3"
```

Without -u/-P should refuse (`Connection error: Connection Refused: not authorised.`).

## ACL — per-user permissions

ACL file — user permissions on topics:

```bash
ssh root@<HOST> 'cat > /etc/mosquitto/acl/default.conf' <<'EOF'
# Default — anonymous deny
topic deny #

# user "admin" — full access
user admin
topic readwrite #

# user "frontend" — read /devices/ only, write /devices/+/controls/+/on
user frontend
topic read /devices/#
topic write /devices/+/controls/+/on

# user "external_app" — only its own namespace
user external_app
topic readwrite app/external_app/#
EOF
ssh root@<HOST> 'systemctl reload mosquitto'   # ACLs reload (no restart required)
```

Each message is checked against the ACL before publishing. **Internal WB services via the Unix socket are not affected by the ACL** — they have their own section in `00default_listener.conf` (`allow_anonymous true`, no acl_file).

## TLS on port 8883

### Certificates

A self-signed CA + server certificate for home tasks. For production prefer Let's Encrypt (via certbot/acme.sh) with a public domain.

```bash
# self-signed CA + server cert (one-time)
ssh root@<HOST> 'mkdir -p /etc/mosquitto/certs && cd /etc/mosquitto/certs && \
  openssl genrsa -out ca.key 2048 && \
  openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=WB-MQTT-CA" && \
  openssl genrsa -out server.key 2048 && \
  openssl req -new -key server.key -out server.csr -subj "/CN=wirenboard-<SN>.local" && \
  openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 3650 -sha256 && \
  chown mosquitto:mosquitto *.key *.crt && chmod 0640 *.key'
```

### TLS listener

```bash
ssh root@<HOST> 'cat >> /etc/mosquitto/conf.d/10listeners.conf' <<'EOF'

listener 8883
allow_anonymous false
acl_file /etc/mosquitto/acl/default.conf
password_file /etc/mosquitto/passwd/default.conf
cafile /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile /etc/mosquitto/certs/server.key
EOF
ssh root@<HOST> 'systemctl restart mosquitto'
```

### TLS test

```bash
ssh root@<HOST> "mosquitto_sub -h localhost -p 8883 --cafile /etc/mosquitto/certs/ca.crt -u <u> -P <p> -t test -C 1 -W 5"
```

From an external host — distribute `ca.crt` to the client, connect to `wirenboard-<SN>.local:8883`. Self-signed without `--cafile` — `tls_version mismatch`/`certificate verify failed`.

For Let's Encrypt — `cafile` not needed (system CA), `certfile`/`keyfile` point to the certbot paths.

## Bridges — bridges to other brokers

A bridge is a mode where mosquitto itself connects to another broker and copies selected topics back and forth. Typical cases: replication to Home Assistant, copy to cloud, backup broker.

### Example: bridge to Home Assistant

`/etc/mosquitto/conf.d/20bridges.conf`:

```bash
ssh root@<HOST> 'cat > /etc/mosquitto/conf.d/20bridges.conf' <<'EOF'
connection ha-bridge
address ha.local:1883
topic /devices/# out 0 wb/A25NDEMJ/
topic ha/wb/cmd/+ in 0
remote_username <ha_mqtt_user>
remote_password <ha_mqtt_password>
keepalive_interval 60
restart_timeout 10
notifications true
notifications_topic wb/A25NDEMJ/bridge/state
cleansession false
try_private false
EOF
ssh root@<HOST> 'systemctl restart mosquitto'
```

Topic parameter: `<pattern> <direction> <qos> <local-prefix> <remote-prefix>`.
- `out` — publish there (outbound), `in` — pull here, `both` — both directions.
- `wb/A25NDEMJ/` — prefix on the remote side (the topics `wb/A25NDEMJ/devices/...` will be visible there).

`wb-notifications` creates `wb/A25NDEMJ/bridge/state` with `online`/`offline` — convenient for monitoring connectivity.

`cleansession false` is important: on disconnect, messages with QoS≥1 accumulate and are delivered after recovery.

### Bridge with TLS

Add to the connection block:

```
bridge_cafile /etc/mosquitto/certs/ha-ca.crt
bridge_certfile /etc/mosquitto/certs/wb-client.crt
bridge_keyfile /etc/mosquitto/certs/wb-client.key
bridge_insecure false
```

`bridge_insecure true` disables hostname verification — only for debugging.

## Changes without restart

`systemctl reload mosquitto` — only re-reads `password_file` and `acl_file`. Listeners, bridges, TLS — require `restart` (~1 second downtime; WB services on the Unix socket survive it).

## Checking state and active clients

```bash
ssh root@<HOST> "mosquitto_sub -h localhost -t '\$SYS/broker/+' -C 20 -W 2"
# /devices/+/meta/name plus $SYS/broker/clients/connected, $SYS/broker/messages/received/1min etc.
```

`mosquitto_sub` without `-u` against a closed listener → 1883 will refuse, 1883 on the Unix socket (mosquitto_sub auto-picks hostname=localhost:1883 by default). To hit the Unix socket: `mosquitto_sub -L mqtt://localhost:1883/<topic>` or connect with `mosquitto_sub -h /var/run/mosquitto/mosquitto.sock` — doesn't work in some versions, easier via 1883.

## Backup and FIT

`/etc/mosquitto/conf.d/`, `/etc/mosquitto/passwd/`, `/etc/mosquitto/acl/`, `/etc/mosquitto/certs/` — all do NOT survive FIT. Via `/wb-controller-backup` they get picked up (some `dpkg --verify` will flag changes, and core-tar will capture them as modified configs).

## Pitfalls

- **`per_listener_settings false`** (default in the Debian package) — `allow_anonymous` applies globally, separate mode for the Unix socket is impossible. The WB config has `per_listener_settings true` — don't reset it.
- **Editing `/etc/mosquitto/mosquitto.conf` directly** — everything you need belongs in `/etc/mosquitto/conf.d/`. The base file may be overwritten by an update.
- **Closed 1883 anonymous, forgot about wb services** — wb services use the Unix socket (`00default_listener.conf`, separate mode), they aren't affected. But if you switch `per_listener_settings false` — WB services break.
- **mosquitto_passwd without `-c` for a new file** — the password isn't saved (no file). With `-c` — overwrites all existing users. After the first user — without `-c`.
- **password_file without reload** — passwords change on `systemctl reload mosquitto`. A full restart isn't needed.
- **ACL without an explicit deny `topic deny #`** — anonymous user (if allow_anonymous true) gets full readwrite by default.
- **Bridge without `cleansession false`** — you'll lose messages on disconnect.
- **Bridge with `try_private true`** is a mosquitto.conf-only feature — for non-mosquitto brokers leave it `false`.
- **TLS certificate expired** — `journalctl -u mosquitto` will show it, and clients get `tls handshake failure`. Renew via certbot or regenerate self-signed.
- **Permissions on `/etc/mosquitto/passwd/default.conf`** — must be `mosquitto:mosquitto 0640`, otherwise mosquitto can't read it (visible in logs: `Unable to open password file ... Permission denied`).

## Documentation

- mosquitto.conf: `man mosquitto.conf`, <https://mosquitto.org/man/mosquitto-conf-5.html>
- ACL: <https://mosquitto.org/documentation/dynamic-security/>
- mosquitto_passwd: <https://mosquitto.org/man/mosquitto_passwd-1.html>
- Bridges: <https://mosquitto.org/documentation/bridges/>
