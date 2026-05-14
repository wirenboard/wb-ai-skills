---
name: wb-mqtt-broker
description: "Mosquitto MQTT broker administration on Wiren Board — listeners, users, ACLs, password files, TLS, bridges to external brokers. /etc/mosquitto/conf.d/. Use when user mentions MQTT broker config, mosquitto, MQTT auth/password, MQTT TLS, external MQTT bridge, broker not running, MQTT client can't connect from outside."
allowed-tools: Bash Read Write WebFetch
---

# mqtt-broker

## CRITICAL RULES

> **NEVER call `wb-cli` without `--json` from an agent.**
> Human-mode output is unparseable; always use:
> `wb-cli --json <command>`
> This applies to every call including help: `wb-cli --json <group> --help`.

**`<HOST>` variable:** in all examples below `<HOST>` means `wirenboard-<SN>.local`, where `<SN>` is the serial number (e.g. `wirenboard-AABBCCDD.local`). Substitute the real address.

`mosquitto` on a WB controller is the main MQTT broker through which all WB services and user applications communicate. Managed via `/etc/mosquitto/conf.d/*.conf` (DON'T edit `mosquitto.conf` directly).

Load this on: "open MQTT externally", "MQTT needs passwords", "set up TLS", "bridge to cloud", "bridge to HA", "can't connect to MQTT from laptop", "mosquitto", "ACL for MQTT", "passwords on the broker", "encrypt MQTT".

## Config structure

```
/etc/mosquitto/mosquitto.conf            # includes 3 directories in order:
  /usr/share/wb-configs/mosquitto/        # WB defaults (DON'T touch)
  /etc/mosquitto/conf.d/                  # user — write here
  /usr/share/wb-configs/mosquitto-post/   # WB post (DON'T touch)

/etc/mosquitto/conf.d/
├── 00default_listener.conf   # Unix socket for WB services — pre-configured; override only if you know what you're doing
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
ssh root@<HOST> "wb-cli --json mqtt sub '\$SYS/#' --count 5"        # broker system stats
ssh root@<HOST> "wb-cli --json mqtt sub '\$SYS/broker/clients/connected' --count 1"
```

### Reading/writing device values via wb-cli

For reading retained MQTT values (device controls, meta), prefer `wb-cli`:

```bash
ssh root@<HOST> wb-cli --json mqtt read '/devices/wb-mr6c_2/controls/K1'
ssh root@<HOST> wb-cli --json mqtt write '/devices/wb-mr6c_2/controls/K1/on' 1
ssh root@<HOST> wb-cli --json mqtt list '/devices/+/meta/name'
ssh root@<HOST> wb-cli --json dev wb-mr6c_2      # all controls with types and values
```

Use raw `mosquitto_sub`/`mosquitto_pub` only when `wb-cli` can't help: broker config testing with `-u`/`-P` auth flags (wb-cli connects via Unix socket, not TCP), and TLS certificate verification with `--cafile`.

### Verbose PUBLISH tracing — `wb-cli mqtt-debug`

To find **which MQTT client** publishes to a given topic (wb-rules, web UI, an external client, a misbehaving driver), use the dedicated `wb-cli mqtt-debug` plugin instead of editing `/etc/mosquitto/conf.d/` by hand. It writes the same `log_type all` drop-in you would write manually, restarts `mosquitto`, parses every `Received PUBLISH …` line out of the journal into structured JSON records, then restores the previous state when done.

Quick form:

```bash
ssh root@<HOST> "wb-cli --json mqtt-debug capture --seconds 60 \
    --topic '/devices/wb-mr6c_7/controls/K1' --client-id wb-rules"
```

For multi-filter captures, MQTT wildcards (`+`, `#`), persistent toggle (`enable`/`status`/`disable`), long background captures with `--output`, the JSON record schema, and the `client_id` lookup table for matching ID → process — see **`references/mqtt-debug.md`**.

## Authentication: passwords and ACL

External listeners (port 1883 / 8883) need `allow_anonymous false` + a password file (`mosquitto_passwd -c …`) + an ACL file (per-user topic permissions). The internal `00default_listener.conf` keeps anonymous-allow over the Unix socket so WB services aren't affected — this is what `per_listener_settings true` enables; don't reset it.

ACL reloads on `systemctl reload mosquitto`; passwords too. Listener / TLS / bridge changes need `restart`.

For the full procedure (create password file, edit listener, test; ACL example with admin / frontend / external_app users) — see **`references/auth.md`**.

## TLS on port 8883 and bridges to other brokers

TLS listener on 8883 uses a CA + server cert (self-signed for home, Let's Encrypt for production) plus the same password / ACL files. A bridge is a mode where mosquitto connects out to another broker and copies selected topics in/out — typical use: replication to Home Assistant, copy to cloud, backup broker. `cleansession false` keeps QoS≥1 messages across disconnects.

For full certificate generation, listener config, bridge config (Home Assistant example), and TLS-on-bridge setup — see **`references/tls-and-bridges.md`**.

## Changes without restart

`systemctl reload mosquitto` — only re-reads `password_file` and `acl_file`. Listeners, bridges, TLS — require `restart` (~1 second downtime; WB services on the Unix socket survive it).

## Checking state and active clients

```bash
ssh root@<HOST> "wb-cli --json mqtt sub '\$SYS/broker/+' --count 20 --timeout 2"
# $SYS/broker/clients/connected, $SYS/broker/messages/received/1min etc.
ssh root@<HOST> wb-cli --json dev                   # all WB devices with names (faster than raw sub)
```

`mosquitto_sub` without `-u` against a closed listener → 1883 will refuse, 1883 on the Unix socket (mosquitto_sub auto-picks hostname=localhost:1883 by default). To hit the Unix socket: `mosquitto_sub -L mqtt://localhost:1883/<topic>` or connect with `mosquitto_sub -h /var/run/mosquitto/mosquitto.sock` — doesn't work in some versions, easier via 1883.

## Backup and FIT

`/etc/mosquitto/conf.d/`, `/etc/mosquitto/passwd/`, `/etc/mosquitto/acl/`, `/etc/mosquitto/certs/` — all do NOT survive FIT. Via `/wb-controller-backup` they get picked up (some `dpkg --verify` will flag changes, and core-tar will capture them as modified configs). For a full list of what survives FIT, see `wb-controller-backup` skill.

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

## What the agent does NOT do

- **Edit `/etc/mosquitto/mosquitto.conf` directly.** All custom config goes in `/etc/mosquitto/conf.d/*.conf` — the base file may be overwritten on package update.
- **Set `per_listener_settings false`** in WB configs. The Unix-socket-anonymous + 1883-authed split depends on `per_listener_settings true`; flipping it locks out internal WB services.
- **Use `mosquitto_passwd -c` on an already-populated file.** `-c` creates fresh, overwriting all existing users.
- **`systemctl restart mosquitto`** for ACL or password changes — those reload with `systemctl reload mosquitto` (no downtime).
- **Store broker passwords / TLS keys in a repo or commit them.** `/etc/mosquitto/passwd/`, `/etc/mosquitto/certs/`, `bridge_password` lines — keep out of version control.
- **Bridge to an external broker without `cleansession false`** — QoS≥1 messages get dropped on disconnect.
- **Use `bridge_insecure true`** outside of one-off debugging — it disables hostname verification.

## When to ask the user

- About to open port 1883 with `allow_anonymous true` on a network-reachable listener — confirm; this exposes the broker to LAN.
- Choosing between self-signed TLS and Let's Encrypt — outcome depends on whether the controller has a public DNS name; ask.
- Enabling a bridge to an external broker — confirm credentials and topic prefix (typos here are silent).
- Replacing existing ACL with a stricter one — surface which users / services lose access (frontend, external_app may go quiet).
- Certificate expiry approaching (< 30 days from `journalctl`) — ask whether to renew or accept the warning until later.

## Documentation

- mosquitto.conf: `man mosquitto.conf`, <https://mosquitto.org/man/mosquitto-conf-5.html>
- ACL: <https://mosquitto.org/documentation/dynamic-security/>
- mosquitto_passwd: <https://mosquitto.org/man/mosquitto_passwd-1.html>
- Bridges: <https://mosquitto.org/documentation/bridges/>
