---
name: wiren-board
description: "Master skill for Wiren Board controllers. Discovery, SSH, wb-cli usage, troubleshooting patterns, documentation lookup. Load this first."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# Wiren Board — master skill

You manage **Wiren Board** home/building automation controllers over SSH.

## Discovery

```bash
avahi-browse -tpr _wirenboard._tcp 2>/dev/null | grep '^=' | awk -F';' '{print $4, $8}'
```

Serial number: 8 chars (e.g. `A25NDEMJ`). Hostname: `wirenboard-<SN>`.

## SSH convention

```bash
ssh root@wirenboard-A25NDEMJ wb-cli info
```

Non-interactive, key-based auth. All wb-cli commands return JSON on stdout.

## wb-cli — the primary tool

Runs **on the controller**. Check it's there: `ssh root@<HOST> 'command -v wb-cli && wb-cli --version'`. If missing — install (see below).

**Rule: before first use of any command group — `wb-cli <group> --help`.**

### Install wb-cli on a controller

Try apt first; if the package isn't in the controller's repos, fall back to the latest GitHub release:

```bash
# 1) Try the apt repo (works once wb-cli is published to wirenboard repos)
ssh root@<HOST> 'apt-get update && apt-get -y install wb-cli' || \

# 2) Fallback: pull the latest .deb from GitHub Releases
ssh root@<HOST> 'set -e
  cd /tmp
  URL=$(curl -fsSL https://api.github.com/repos/wirenboard/wb-ai-skills/releases/latest \
        | grep -oE "https://[^\"]+wb-cli_[^\"]+\.deb" | head -1)
  [ -n "$URL" ] || { echo "no .deb in latest release" >&2; exit 1; }
  curl -fsSL -o wb-cli.deb "$URL"
  apt-get install -y ./wb-cli.deb || dpkg -i wb-cli.deb || {
    apt-get install -y -f
    dpkg -i wb-cli.deb
  }
  wb-cli --version'
```

Notes:
- `wb-cli` is an `_all.deb` (arch-independent), works on any wb6/wb7 firmware ≥ bullseye.
- Runtime deps (`python3-mqttrpc`, `python3-wb-common`, `mosquitto-clients`, `jq`) live in the wirenboard apt repo, which is preconfigured on every controller — `apt-get install -y -f` resolves them.
- Verify with `wb-cli info` (returns serial number, fw, uptime).

### Output contract

- Success: `{"data": {...}}` — object, `snake_case` keys.
- Error: `{"error": {"code": "SCREAMING_SNAKE", "message": "...", "hint": "...", "details": {...}}}`.
- Exit codes: 0 success, 1 domain, 2 usage, 3 environment.

### Key commands

```bash
wb-cli info                              # serial, firmware, board, uptime
wb-cli devices list                      # all devices with names
wb-cli devices controls <device>         # values, types, readonly, errors
wb-cli devices set <device> <ctrl> <val> # turn on/off, write value
wb-cli mqtt read <topic>                 # read retained value
wb-cli mqtt write <topic> <value>        # publish
wb-cli confed load <path>                # load config via confed RPC
wb-cli rules list                        # automation rules
wb-cli history get <device/control>      # time-series from db
wb-cli modbus scan --port /dev/ttyRS485-1
wb-cli audit                             # quick health check
```

### Standard Linux — use SSH directly

```bash
ssh root@<HOST> systemctl status wb-mqtt-serial
ssh root@<HOST> journalctl -u wb-rules -n 50
ssh root@<HOST> docker ps
ssh root@<HOST> apt-get install <package>
ssh root@<HOST> ip addr show
```

## Docker on WB

Standard Docker CE installed via `wb-docker-manager.sh`. Key WB-specific rule: **all Docker data and compose projects go in `/mnt/data/`** (larger partition, survives firmware updates).

```bash
ssh root@<HOST> 'docker compose -f /mnt/data/homeassistant/docker-compose.yml up -d'
```

## Troubleshooting patterns

### Kernel mismatch (most common WB issue)

```bash
ssh root@<HOST> 'uname -r; cat /boot/Image.version 2>/dev/null || echo unknown'
```

If versions differ — **reboot is the only fix**. Kernel modules won't load, Docker/iptables/network may break. Don't try modprobe workarounds.

### Docker iptables fix (after kernel is OK)

```bash
ssh root@<HOST> 'update-alternatives --set iptables /usr/sbin/iptables-legacy && systemctl restart docker'
```

### Quick diagnostic sequence

```bash
ssh root@<HOST> 'systemctl list-units --state=failed --no-pager'
ssh root@<HOST> 'df -h / /mnt/data'
ssh root@<HOST> 'wb-cli audit'
```

## Documentation lookup

Before fixing an unfamiliar component, check the wiki:

```
WebFetch('https://wiki.wirenboard.com/wiki/<Component>')
```

Common pages: `Docker`, `Modbus`, `Home_Assistant`, `Wiren_Board_Cloud`, `wb-rules`.

## Specialized skills

| Need | Skill |
|---|---|
| wb-rules JavaScript automation (defineRule, virtual devices, cron, ES5) | `/wb-rules` |
| General troubleshooting (failed services, disk, kernel, Docker) | `/wb-troubleshooting` |
| RS-485 / Modbus bus debugging (CRC, timeouts, debug capture) | `/wb-troubleshooting-serial` |
| No-code declarative scenarios (thermostat, lighting, schedule) | `/wb-scenarios` |
| Custom Modbus device templates (registers, endianness, parameters) | `/wb-serial-templates` |
| Network setup (WiFi, 4G/GSM, VPN, failover, modem diagnostics) | `/wb-network` |
| MQTT broker config (auth, ACL, TLS, bridges to HA/cloud) | `/wb-mqtt-broker` |
| Full controller backup and restore | `/wb-controller-backup` |
| Zigbee devices via zigbee2mqtt (pairing, OTA, native vs Docker) | `/wb-zigbee` |

## Safety

- **Back up before destructive operations** (confed save, rules delete, modbus add-devices).
- **Never write to MQTT controls you don't understand** — some control physical outputs.
- **Long operations** (apt upgrade, factoryreset) — use `wb-cli job run`, not raw SSH.
