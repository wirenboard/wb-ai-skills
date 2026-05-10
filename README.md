# wb-ai-skills

**Talk to your [Wiren Board](https://wirenboard.com) controllers from an AI assistant.**

Drop the chat box into [Claude Code](https://claude.ai/code) or [opencode](https://opencode.ai), type a question — the assistant figures out which controller, runs SSH/MQTT/Modbus commands, reads logs, edits configs, and reports back.

```
> /wiren-board
> something is wrong on A25NDEMJ — find out what

→ ssh A25NDEMJ → systemctl --failed → fstrim.service is failing
→ journalctl -u fstrim → status=64/USAGE, /mnt/sdcard not mounted
→ explanation in plain English + suggested override-conf to fix it
```

No new desktop app. No vendor lock-in. The assistant you already use, plus skill files telling it *how* to drive a Wiren Board controller well.

---

## What is this and why

The package contains **skills** — Markdown files telling the LLM how to work with WB. The LLM uses its built-in `Bash` tool to run `ssh`, `mosquitto_*` and `avahi-browse` directly. Setup ≈5 min, no dependencies beyond the host CLI utilities.

Nothing runs **on** the controller. Stock SSH + mosquitto + avahi is all the controller needs. Survives factoryreset and FIT firmware reflash without ssh-key churn.

---

## What you can ask

After loading the master skill `/wiren-board`, a fresh assistant session can do all of this without further hand-holding:

- **Discovery & status** — "find all WB controllers in the LAN", "what firmware does A25NDEMJ run?", "show load and disk on every controller"
- **Diagnostics** — "why is wb-mqtt-serial unhappy?", "any failed services?", "errors in the journal in the last hour"
- **Modbus** — "scan the bus, list devices", "WB-MAI6 channels in1..in6 — turn them all on", "show me the WB-MR6C template"
- **MQTT** — "what's `/devices/wb-mr6c_2/controls/K1`?", "publish ON to `K1/on`", "list every device with its controls"
- **Rules & scenarios** — "make a rule: when motion fires, turn on the light for 60 s", "create a thermostat scenario for the living room"
- **History** — "plot CPU temperature for the last 24 h as SVG", "average current draw last week"
- **Backup & update** — "make a full backup before `apt upgrade`", "what packages will be upgraded?", "factoryreset this test controller"
- **Network & cloud** — "is internet working?", "switch the uplink to sim2", "is wb-cloud-agent connected?"

Each is one sentence to the LLM. The LLM picks commands, runs them, asks for confirmation on destructive ops, reports back.

---

## Quick install

```bash
sudo apt install avahi-utils jq sshpass

git clone https://github.com/wirenboard/wb-ai-skills.git
cd wb-ai-skills

./install-skills.sh claude --global       # for Claude Code
# or
./install-skills.sh opencode --global     # for opencode
```

That's it. Open Claude Code / opencode and try `/wiren-board` (see [Try it](#try-it)).

`mosquitto_sub` / `mosquitto_pub` run **on the controller** (over SSH) — no `mosquitto-clients` needed on the host.

### SSH access to controllers

Default factory creds are `root` / `wirenboard`. Two ways:

1. **SSH key (recommended)** — `ssh-copy-id -o StrictHostKeyChecking=accept-new root@wirenboard-A25NDEMJ.local`. Then no `sshpass` needed.
2. **Password** — keep the `wirenboard` default. `sshpass` package required.

The skills use `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null`, so factoryreset and firmware reflash don't break SSH access.

### Try it

In Claude Code:

```
> /wiren-board
> find every controller in the network and show release + uptime
```

In opencode:

```
> @wiren-board find controllers and show release + uptime
```

Expected: a list with `sn`, `host`, `release`, `uptime`. If it's empty, see [Troubleshooting](#troubleshooting).

---

## Skills (21)

| Skill | Ask the assistant for... |
|---|---|
| `wiren-board` | **Master skill** — load this first; it knows about all the others |
| `wb-mqtt-serial` | Modbus/RS-485: enable channels, add devices, edit config |
| `wb-serial-templates` | Custom Modbus templates for non-WB devices |
| `wb-rules` | Write/debug JS rules (ES5), virtual devices, cron, alarms |
| `wb-scenarios` | Web UI scenarios: lighting, thermostat, schedules |
| `wb-notifications` | Telegram bot, email (msmtp), SMS via the modem |
| `wb-troubleshooting` | "Something broke" — failed services, kernel mismatch, disk |
| `wb-troubleshooting-serial` | RS-485 debug: CRC, timeouts, raw packet capture |
| `wb-services` | systemd: drop-ins, custom services and timers |
| `wb-network` | NetworkManager + wb-connection-manager (eth/wifi/4G/VPN) |
| `wb-cloud` | Wiren Board Cloud agent: link/unlink/diagnose |
| `wb-mqtt-broker` | mosquitto admin: passwords, ACLs, bridges, TLS |
| `wb-controller-backup` | Tar backup with RESTORE.md, including Docker volumes |
| `wb-controller-update` | `apt upgrade`, switch release, factoryreset |
| `wb-hardware-modules` | Configure MOD1-4 / WBIO / Zigbee / CAN slots |
| `wb-software-install` | Docker-by-default install of Node-RED / HA / Grafana / Z2M |
| `wb-zigbee` | Pairing, control, OTA via zigbee2mqtt |
| `wb-history` | Query wb-mqtt-db, render SVG / Mermaid charts |
| `wb-bugreport` | Compose a bug report for support, gather diag archive |
| `wb-diagrams` | Mermaid diagrams of automation logic (controller-independent) |
| `wb-documentation-search` | Search wirenboard.com/wiki and GitHub (controller-independent) |

---

## Under the hood

```
                       ┌──────────────────┐
                       │  Claude Code     │
       you ──────────► │  / opencode      │
       (chat)          │                  │
                       └────┬─────────────┘
                            │ Bash tool (ssh, mosquitto_*, avahi-browse)
                            ▼
              ┌─────────────────────┐
              │  Wiren Board ctrl   │
              │  stock sshd +       │
              │  stock mosquitto    │
              └─────────────────────┘
```

The LLM runs `mosquitto_sub` / `mosquitto_pub` on the controller via SSH (not locally). Locally it only spawns `ssh`/`sshpass` and `avahi-browse`.

### Things to know

- **SSH host key.** Skills use `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null`. After factoryreset / FIT reflash the controller's host key changes; we don't fight it. Local-network controllers are a trusted environment.
- **MQTT errors are typed.** `<...>/meta/error` is parsed into `{read, write, periodMiss}` per [WB Conventions](https://github.com/wirenboard/conventions). When `read=true` the value topic still holds the **last-known-good** value.
- **Names with spaces work.** WB-MR6C exposes controls named `Input 0`, `Input 0 counter`. Skills use `mosquitto_sub -F '%t\t%p'` so spaces inside names don't get clipped.

### Repo layout

- `skills/bash/` — 21 skills with shell recipes. Source of truth for domain knowledge (RPC formats, Modbus quirks, wb-rules ES5 limits).
- `install-skills.sh` — installer for Claude Code and opencode.
- `VERSION` — single source of truth; printed by the master skill.

---

## Troubleshooting

**`avahi-browse` returns nothing.** In order of likelihood:

1. `avahi-daemon` isn't running on the host — `systemctl status avahi-daemon`, start if needed.
2. Multicast is blocked between segments — mDNS only works in one broadcast domain (no NAT, no VPN, same VLAN).
3. Controller is in WB-AP mode and host isn't on its WiFi.

Workaround: connect by IP — `ssh root@192.168.x.y`. Bypasses mDNS.

**SSH timeout / "handshake failure".**

1. Controller just booted (uptime < 1 min) — `sshd` is still bringing up crypto, wait 30-60 s.
2. Stale `~/.ssh/known_hosts` — `ssh-keygen -R wirenboard-A25NDEMJ.local`.
3. Password changed — after factoryreset root's password is back to `wirenboard`. Custom password no longer matches.

**`apt-get update` returns 403 on a fresh-from-factory controller.** `deb.wirenboard.com` is behind a CDN that occasionally caches a stale 403 (24 h TTL). Wait it out, or `wb-release -t wb-2602` to switch to a fresher release (see <https://wirenboard.com/wiki/WB_Software_Releases>).

---

## Uninstall

```bash
# Skills (Claude Code — they're symlinks):
find ~/.claude/skills -maxdepth 1 -type l -lname '*wb-ai-skills/skills/*' -delete

# Skills (opencode — flat .md files):
ls ~/.config/opencode/agents/    # remove relevant files

# Artifacts on a controller (backups, diag captures):
ssh root@<host> 'rm -rf /mnt/data/ai/wb-ai-skills'
```

---

## Requirements

- **Host:** Linux (Debian/Ubuntu tested). macOS — not tested; mDNS would need a `dns-sd` shim instead of `avahi-browse`. Windows — no.
- **Client:** Claude Code CLI or opencode.
- **Controllers:** anything reachable over SSH on stock firmware. Tested on wb7 (wb-2410, wb-2602) and wb8 (wb-2507).

## License

MIT — see [LICENSE](LICENSE).

## Related

- [`wb-ai-helper-desktop`](https://github.com/wirenboard/wb-ai-helper-desktop) — sibling project: a standalone desktop chat with its own DB and UI, talks to controllers over SSH/MQTT, encapsulates Anthropic / OpenAI / AITunnel APIs. Different deployment model: there you bring your API key; here you bring your existing Claude Code or opencode setup.
- [Wiren Board MQTT Conventions](https://github.com/wirenboard/conventions) — the spec these skills speak.
