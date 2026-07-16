---
name: wiren-board
description: "Master skill for Wiren Board (WB) controllers — load FIRST whenever user mentions Wiren Board, wirenboard.com, wb6/wb7/wb8/wb-msw hardware, or any wb-* tool. Provides: controller discovery via mDNS, SSH access patterns, wb-cli usage (always --json from an agent!), documentation lookup, common troubleshooting entry point."
allowed-tools: Bash Read Write WebFetch WebSearch
---

# Wiren Board — master skill

## CRITICAL RULES

> **NEVER call `wb-cli` without `--json` from an agent.**
> Human-mode output is unparseable; always use:
> `wb-cli --json <command>`
> This applies to every call including help: `wb-cli --json <group> --help`.

You manage **Wiren Board** home/building automation controllers over SSH.

## Discovery

Find all controllers on the local network (mDNS):

```bash
avahi-browse _workstation._tcp -tpr 2>/dev/null | grep '^=' | grep -i 'wirenboard-' | awk -F';' '{print $7, $8}'
```

Controllers announce themselves as `_workstation._tcp`, not `_wirenboard._tcp`.
Output: `wirenboard-<SN>.local <IP>` (both IPv4 and IPv6 entries).
Serial number: 8 chars (e.g. `A25NDEMJ`). Hostname: `wirenboard-<SN>`.

If avahi returns nothing (mDNS not forwarded, different subnet, or avahi not running):

```bash
# Resolve a specific controller by serial number
avahi-resolve -n wirenboard-A25NDEMJ.local

# Scan the local subnet for all WB controllers (port 22 open, hostname pattern)
nmap -sn 192.168.1.0/24 2>/dev/null | awk '/wirenboard/{print}' 
```

## SSH convention

Default credentials: **user `root`, password `wirenboard`**.

**IMPORTANT — always follow this order when connecting:**

```bash
# Step 1: try key-based auth (BatchMode=yes prevents GUI password prompts)
ssh -o BatchMode=yes -o ConnectTimeout=5 root@<HOST> wb-cli --json info

# Step 2: if step 1 fails — try default password (never wait for a GUI prompt)
sshpass -p wirenboard ssh -o ConnectTimeout=5 root@<HOST> wb-cli --json info

# Step 3: only if both fail — ask the user for credentials
```

**Never run plain `ssh root@<HOST>` without `BatchMode=yes`** — it may trigger a GUI password dialog (ksshaskpass, SSH_ASKPASS) that blocks execution.

## SSH key-based auth

```bash
ssh-copy-id root@<HOST>          # copies ~/.ssh/id_*.pub
```
After this, step 1 succeeds and password is never needed. To disable password auth — edit `/etc/ssh/sshd_config`: set `PasswordAuthentication no`, then `systemctl restart sshd`.

## wb-cli — the primary tool

Runs **on the controller**. Check it's there: `ssh root@<HOST> 'command -v wb-cli && wb-cli --version'`. If missing — install (see below).

**Rule: before first use of any command group — `wb-cli --json <group> --help`.**

### Install wb-cli on a controller

Try apt first; if the package isn't in the controller's repos, fall back to the latest GitHub release:

```bash
# 1) Try the apt repo (works once wb-cli is published to wirenboard repos)
ssh root@<HOST> 'apt update && apt -y install wb-cli' || \

# 2) Fallback: pull the latest .deb from GitHub Releases
ssh root@<HOST> 'set -e
  cd /tmp
  URL=$(curl -fsSL https://api.github.com/repos/wirenboard/wb-ai-skills/releases/latest \
        | grep -oE "https://[^\"]+wb-cli_[^\"]+\.deb" | head -1)
  [ -n "$URL" ] || { echo "no .deb in latest release" >&2; exit 1; }
  curl -fsSL -o wb-cli.deb "$URL"
  apt install -y ./wb-cli.deb || dpkg -i wb-cli.deb || {
    apt install -y -f
    dpkg -i wb-cli.deb
  }
  wb-cli --version'
```

Notes:
- `wb-cli` is an `_all.deb` (arch-independent), works on any wb6/wb7 firmware ≥ bullseye.
- Runtime deps (`python3-mqttrpc`, `python3-wb-common`, `mosquitto-clients`, `jq`) live in the wirenboard apt repo, which is preconfigured on every controller — `apt install -y -f` resolves them.
- Verify with `wb-cli --json info` (returns serial number, fw, uptime).

### Output contract

`wb-cli` defaults to human-friendly output everywhere. **Always pass `--json` (or set `WB_CLI_OUTPUT=json`)** when calling from an agent / script:

```bash
ssh root@<HOST> wb-cli --json dev
```

- Success: `{"data": {...}}` — object, `snake_case` keys.
- Error: `{"error": {"code": "SCREAMING_SNAKE", "message": "...", "details": {...}}}` — `hint` is optional.
- Exit codes: 0 success, 1 domain, 2 usage, 3 environment.

In human mode a stderr spinner / progress bar is drawn during long operations; it never touches stdout, so even mixed-mode output stays parseable.

### Key commands

For the full command list run `wb-cli --help` or `wb-cli <group> --help` on the controller — that is always up to date. Common entry points: `info`, `dev`, `mqtt`, `mqtt-debug`, `rules`, `serial` (incl. `serial wb-fw` firmware update, formerly the standalone `modbus-fw` plugin), `serial-debug`, `audit`, `snapshot`, `job`, `confed`, `history`, `cloud`, `plugins`.

Addressing uses the wb-rules form `<device>/<control>`. Quote names with spaces:

```bash
ssh root@<HOST> wb-cli --json info
ssh root@<HOST> wb-cli --json dev wb-adc/Vin          # read one control
ssh root@<HOST> "wb-cli --json dev 'wb-mdm3_5/Channel 1 Dimming Level' 30"
ssh root@<HOST> wb-cli --json audit
```

### Standard Linux — use SSH directly

```bash
ssh root@<HOST> systemctl status wb-mqtt-serial
ssh root@<HOST> journalctl -u wb-rules -n 50
ssh root@<HOST> docker ps
ssh root@<HOST> apt install <package>
ssh root@<HOST> ip addr show
```

## Docker on WB

Standard Docker CE installed via `wb-docker-manager.sh`. Key WB-specific rule: **all Docker data and compose projects go in `/mnt/data/`** (larger partition, survives firmware updates).

```bash
ssh root@<HOST> 'docker compose -f /mnt/data/homeassistant/docker-compose.yml up -d'
```

## Firmware / package upgrade

There is **no `wb-update-manager` command** — that does not exist. Use standard apt:

```bash
# Check what can be updated (fast — plain SSH is fine)
ssh root@<HOST> 'apt update -qq && apt --simulate upgrade | grep "^Inst"'

# Install updates — takes minutes, use job:
ssh root@<HOST> 'wb-cli --json job run apt-upgrade "apt update && apt -y upgrade 2>&1"'
ssh root@<HOST> 'wb-cli --json job wait apt-upgrade'
ssh root@<HOST> 'wb-cli --json job tail apt-upgrade'
```

**WB release model:** A release (e.g. `wb-2602` = February 2026) is a named snapshot of package versions. There are **no packages named `wb-2603-repo` or similar** — do not search for them in apt.

To check what releases exist and which is latest — fetch this URL (no auth required, never use `gh api` or `gh cli` for this):

```
WebFetch("https://raw.githubusercontent.com/wirenboard/wb-releases/main/releases.yaml")
```

The top-level keys under `releases:` are the available release names. The first (topmost) entry is the latest.

Running `apt upgrade` updates packages within the current release track; it also bumps `release_name` when WB publishes a new release to the stable repo.

After a reboot, verify: `wb-cli --json info`. If kernel mismatch after upgrade — see `wb-troubleshooting` skill.

## Factory reset

**Erases /etc and /mnt/data/etc. Back up first (see wb-controller-backup skill).**
```bash
ssh root@<HOST> wb-cli --json job run factory-reset "wb-factoryreset 2>&1"
```
Controller reboots with default config. SSH will work with default credentials (root/wirenboard).

## apt package pinning

Hold a package at current version:
```bash
ssh root@<HOST> "apt-mark hold <package>"
ssh root@<HOST> "apt-mark showhold"       # list held packages
ssh root@<HOST> "apt-mark unhold <package>"
```

## Troubleshooting patterns

### Kernel mismatch

Kernel mismatch after upgrade — see `wb-troubleshooting` skill.

### Docker iptables fix (after kernel is OK)

```bash
ssh root@<HOST> 'update-alternatives --set iptables /usr/sbin/iptables-legacy && systemctl restart docker'
```

### Quick diagnostic sequence

```bash
ssh root@<HOST> 'wb-cli --json audit'            # failed units + identity in one call
ssh root@<HOST> 'df -h / /mnt/data'              # disk: only thing audit does not check yet
```

`wb-cli audit` already enumerates failed services (and reports them in the `failed_units` check), so a separate `systemctl --failed` is redundant.

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
| RS-485 / Modbus: templates, confed config, diagnostics (CRC, timeouts) | `/wb-serial` |
| Network setup (WiFi, 4G/GSM, VPN, failover, modem diagnostics) | `/wb-network` |
| MQTT broker config (auth, ACL, TLS, bridges to HA/cloud) | `/wb-mqtt-broker` |
| Full controller backup and restore | `/wb-controller-backup` |
| Zigbee devices via zigbee2mqtt (pairing, OTA, native vs Docker) | `/wb-zigbee` |
| Software development / integrations for WB (custom daemons, protocol bridges, MQTT conventions, MQTT-RPC, Debian packaging) | `/wb-dev` |
| Reproduce a reported bug, find/prove the root cause, investigate a regression ("broke after an update"), write a defensible bug report | `/wb-rca` |
| Test / reproduce a bug in the web UI (homeui) in a real browser | `/wb-webui-test` |

**Which of the "something is wrong" skills?** They are complementary lanes, not rivals:
- **Fix it / restore service now**, generic diagnostics, diag archive → `/wb-troubleshooting`.
- **Prove *why* it broke**, reproduce it, confirm a regression, produce a bug report → `/wb-rca`.
- The symptom is in the **web UI** and you need to see it in a browser → `/wb-webui-test` (hand off to `/wb-rca` once you need the root cause).
- A specific bus/domain misbehaves → the component skill (`/wb-serial`, `/wb-network`, `/wb-zigbee`, `/wb-mqtt-broker`), escalating to `/wb-rca` to prove a cross-version regression.

## Third-party integrations

For components not covered by a dedicated skill — always start with `WebFetch` on the WB wiki page, then standard component docs:

| Component | Wiki page |
|---|---|
| InfluxDB, Grafana | `WebFetch('https://wiki.wirenboard.com/wiki/InfluxDB')` |
| Node-RED | `WebFetch('https://wiki.wirenboard.com/wiki/Node-RED')` |
| Home Assistant | `WebFetch('https://wiki.wirenboard.com/wiki/Home_Assistant')` |
| nginx / SSL on controller | `WebFetch('https://wiki.wirenboard.com/wiki/Nginx')` + standard nginx / certbot docs |
| Docker on controller | `WebFetch('https://wiki.wirenboard.com/wiki/Docker')` |

**Installing software on a controller:** WB has a small root partition. Install via:
1. WB-packaged `.deb` from the wirenboard apt repo (e.g. `zigbee2mqtt` built by WB maintainers) — preferred.
2. Docker — **follow the WB wiki, not generic Docker docs**: `WebFetch('https://wiki.wirenboard.com/wiki/Docker')`. Docker is pre-configured to store images in `/mnt/data` (not root); generic `apt install docker-ce` breaks this. Use `docker compose` from `/mnt/data/etc/docker/`.
3. Direct `apt install` of standard Debian packages — only if they're small and in the wirenboard repo. Large packages (Node.js runtimes, databases) must go via Docker or `/mnt/data`.

## Safety

- **Back up before destructive operations** (confed save, rules delete, modbus add-devices).
- **Never write to MQTT controls you don't understand** — some control physical outputs.
- **Any operation expected to take more than 20–30 seconds** — use `wb-cli job run`, not plain SSH. This includes `apt update`, `apt upgrade`, `apt install`, tar archives, modbus firmware updates, factory reset. Plain SSH will appear to hang, block the agent, and may timeout mid-operation leaving the system in an inconsistent state.

```bash
# Wrong — blocks the agent for minutes:
ssh root@<HOST> 'apt update && apt -y upgrade'

# Correct — returns immediately, agent polls for completion:
ssh root@<HOST> 'wb-cli --json job run apt-upgrade "apt update && apt -y upgrade 2>&1"'
ssh root@<HOST> 'wb-cli --json job wait apt-upgrade'
ssh root@<HOST> 'wb-cli --json job tail apt-upgrade'
```

## What the agent does NOT do

- **Call `wb-cli` without `--json`.** Human-mode output is unparseable. Already restated in CRITICAL RULES — it bears repeating because half the agent failures on WB skills trace back to this.
- **Run long-running ops via plain SSH.** `apt`, tar, modbus firmware update — wrap in `wb-cli job run`. Plain SSH appears to hang and may timeout mid-operation, leaving the system half-changed.
- **Install Docker via generic `apt install docker-ce`.** Breaks `/mnt/data` storage path. Use `wb-docker-manager.sh` from the WB community repo.
- **Write to MQTT controls without understanding the effect.** Some `/devices/.../on` write closes a relay → drives a real physical output.
- **Trigger factory reset / FIT upgrade** without explicit user confirmation — both are minutes-long, destructive operations.
- **Decide which controller to act on** when discovery returns multiple — surface the list.
- **Modify `git config`, SSH keys, or `/root/.ssh/authorized_keys`** on the controller as a side effect of another operation.

## When to ask the user

- Discovery returns more than one controller — ask which one.
- About to run a firmware (FIT) upgrade or factory reset — confirm strongly; both rewrite the rootfs.
- About to `apt upgrade` while the controller is in production — confirm window; restart-required packages will bounce services.
- The user's request maps to two different skills (e.g. "no internet" could be `wb-network` or `wb-troubleshooting`) — confirm scope.
- A wb-* tool isn't behaving as documented (output format differs from spec) — surface the discrepancy; do not silently rewrite logic around the new behavior.
