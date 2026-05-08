# wb-ai-skills

**Talk to your [Wiren Board](https://wirenboard.com) controllers from an AI assistant.**

Drop the chat box into [Claude Code](https://claude.ai/code) or [opencode](https://opencode.ai), type a question — the assistant figures out which controller, runs SSH/MQTT/Modbus commands, reads logs, edits configs, and reports back.

```
> /wiren-board
> something is wrong on A25NDEMJ — find out what

→ wb_failed → fstrim.service is failing
→ wb_logs unit=fstrim → status=64/USAGE, /mnt/sdcard not mounted
→ explanation in plain English + suggested override-conf to fix it
```

No new desktop app. No vendor lock-in. The assistant you already use, plus a typed toolbox for WB plus skill files telling it *how* to use them well.

---

## What is this and why

The package contains **skills** (Markdown files telling the LLM how to work with WB) and an optional **MCP server** (43 typed tools the LLM calls instead of raw shell). Two ways to use them:

- **Bash flavor** — skills only. The LLM uses its built-in `Bash` tool to run `ssh`, `mosquitto_*` and `avahi-browse` directly. Setup ≈5 min, no dependencies beyond the host CLI utilities.
- **MCP flavor** — skills + a Bun-based MCP server. The LLM calls structured tools like `wb_modbus_scan`, `wb_history_chart`, `wb_systemd_unit`. Typed input/output, no shell-quoting accidents, ready-made charts. Setup ≈10 min.

Pick one — never both. The two skill sets share the same names; the LLM client would only see one of each anyway. **MCP flavor is recommended for daily use**; bash flavor is the no-Bun fallback.

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

Each is one sentence to the LLM. The LLM picks tools, runs them, asks for confirmation on destructive ops, reports back.

---

## Quick install

The repo is the only thing you clone. Run **one** of the two install scripts below. Both end with the same one-liner you type in your AI client.

### Prerequisites

| | Bash flavor | MCP flavor |
|---|---|---|
| **Host packages** | `avahi-utils`, `jq`, `sshpass` (only with password auth) | `avahi-utils`, [Bun](https://bun.sh) 1.3+, `sshpass` (only with password auth) |
| **On the controller** | Stock SSH + mosquitto (already there) | Same |
| **Setup time** | 5 min | 10 min |

`mosquitto_sub` / `mosquitto_pub` run **on the controller** (over SSH) in both flavors — no `mosquitto-clients` needed on the host.

### Bash flavor

```bash
sudo apt install avahi-utils jq sshpass

git clone https://github.com/wirenboard/wb-ai-skills.git
cd wb-ai-skills

./install-skills.sh bash claude --global       # for Claude Code
# or
./install-skills.sh bash opencode --global     # for opencode
```

That's it. Open Claude Code / opencode and try `/wiren-board` (see [Try it](#try-it)).

### MCP flavor

```bash
sudo apt install avahi-utils sshpass
curl -fsSL https://bun.sh/install | bash
exec $SHELL    # reload PATH so `bun` is found

git clone https://github.com/wirenboard/wb-ai-skills.git
cd wb-ai-skills/mcp-server && bun install && cd ..

./install-skills.sh mcp claude --global        # or: mcp opencode --global
```

Then register the MCP server with your client. **Claude Code:**

```bash
claude mcp add wiren-board -- bun run "$(pwd)/mcp-server/src/index.ts"
```

Or hand-edit `~/.claude.json`:

```json
{
  "mcpServers": {
    "wiren-board": {
      "command": "bun",
      "args": ["run", "/ABS/PATH/TO/wb-ai-skills/mcp-server/src/index.ts"],
      "env": {
        "WB_SSH_USER": "root",
        "WB_SSH_PASSWORD": "wirenboard",
        "WB_CHART_FORMAT": "svg"
      }
    }
  }
}
```

**opencode** uses a slightly different shape — `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "wiren-board": {
      "type": "local",
      "command": ["bun", "run", "/ABS/PATH/TO/wb-ai-skills/mcp-server/src/index.ts"],
      "environment": { "WB_SSH_USER": "root", "WB_SSH_PASSWORD": "wirenboard" },
      "enabled": true
    }
  }
}
```

Restart the client so it re-reads the config.

### SSH access to controllers

Default factory creds are `root` / `wirenboard`. Two ways:

1. **SSH key (recommended)** — `ssh-copy-id -o StrictHostKeyChecking=accept-new root@wirenboard-A25NDEMJ.local`. Then no `sshpass` and no env vars needed.
2. **Password** — leave `WB_SSH_PASSWORD=wirenboard` (the default). `sshpass` package required.

Both flavors disable strict host-key checking, so factoryreset and firmware reflash don't break SSH access.

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

| Skill | Bash | MCP | Ask the assistant for... |
|---|:---:|:---:|---|
| `wiren-board` | ✓ | ✓ | **Master skill** — load this first; it knows about all the others |
| `wb-mqtt-serial` | ✓ | ✓ | Modbus/RS-485: enable channels, add devices, edit config |
| `wb-serial-templates` | ✓ | ✓ | Custom Modbus templates for non-WB devices |
| `wb-rules` | ✓ | ✓ | Write/debug JS rules (ES5), virtual devices, cron, alarms |
| `wb-scenarios` | ✓ | ✓ | Web UI scenarios: lighting, thermostat, schedules |
| `wb-notifications` | ✓ | ✓ | Telegram bot, email (msmtp), SMS via the modem |
| `wb-troubleshooting` | ✓ | ✓ | "Something broke" — failed services, kernel mismatch, disk |
| `wb-troubleshooting-serial` | ✓ | ✓ | RS-485 debug: CRC, timeouts, raw packet capture |
| `wb-services` | ✓ | ✓ | systemd: drop-ins, custom services and timers |
| `wb-network` | ✓ | ✓ | NetworkManager + wb-connection-manager (eth/wifi/4G/VPN) |
| `wb-cloud` | ✓ | ✓ | Wiren Board Cloud agent: link/unlink/diagnose |
| `wb-mqtt-broker` | ✓ | ✓ | mosquitto admin: passwords, ACLs, bridges, TLS |
| `wb-controller-backup` | ✓ | ✓ | Tar backup with RESTORE.md, including Docker volumes |
| `wb-controller-update` | ✓ | ✓ | `apt upgrade`, switch release, factoryreset |
| `wb-hardware-modules` | ✓ | ✓ | Configure MOD1-4 / WBIO / Zigbee / CAN slots |
| `wb-software-install` | ✓ | ✓ | Docker-by-default install of Node-RED / HA / Grafana / Z2M |
| `wb-zigbee` | ✓ | ✓ | Pairing, control, OTA via zigbee2mqtt |
| `wb-history` | ✓ | ✓ | Query wb-mqtt-db, render SVG / Mermaid charts |
| `wb-bugreport` | ✓ | ✓ | Compose a bug report for support, gather diag archive |
| `wb-diagrams` | ✓ | — | Mermaid diagrams of automation logic (controller-independent) |
| `wb-documentation-search` | ✓ | — | Search wirenboard.com/wiki and GitHub (controller-independent) |

`wb-diagrams` and `wb-documentation-search` work without a controller; the installer pulls them from `skills/bash/` even when you choose mcp-flavor.

---

## MCP tools (43, mcp flavor only)

### Discovery (3)

| Tool | Purpose |
|---|---|
| `wb_discover` | List controllers seen via mDNS + manual entries |
| `wb_probe` | Reachability + uname/release/fwVersion/uptime for one SN |
| `wb_add_controller` | Manually register by hostname/IP (when mDNS is blocked) |

### SSH & files (4)

| Tool | Purpose |
|---|---|
| `wb_ssh_exec` | Synchronous shell command, up to 2 min |
| `wb_ssh_exec_async` | Background task via `systemd-run --collect`, survives SSH disconnect |
| `wb_read_file` | Read up to 64 KB |
| `wb_write_file` | Write via SFTP, any size |

### Async jobs (3)

| Tool | Purpose |
|---|---|
| `wb_job_status` | Active state, exit code, log line count, label |
| `wb_job_tail` | Incremental log reader (`fromLine`/`maxLines`) |
| `wb_job_cancel` | SIGTERM the unit |

Job script and log live in `/mnt/data/ai/wb-ai-skills/jobs/<id>.{sh,log}` (24-hour TTL gc).

### MQTT (4)

| Tool | Purpose |
|---|---|
| `wb_mqtt_read` | Read one retained topic (any, not only WB) |
| `wb_mqtt_write` | Publish to any topic; optional `retain`/`qos` |
| `wb_mqtt_list` | Subscribe by prefix for `timeout` seconds, collect topic→payload |
| `wb_mqtt_rpc` | One-shot RPC over MQTT (wb-mqtt-serial, confed, wbrules, db_logger, wb-device-manager, ...) |

### Devices (3)

| Tool | Purpose |
|---|---|
| `wb_mqtt_devices` | Compact `{id: human-name}` map |
| `wb_mqtt_controls` | Raw topic→payload list for one device |
| `wb_mqtt_inventory` | **Combined view**: devices + driver + parsed error + controls with unpacked meta. Error flags follow [WB Conventions](https://github.com/wirenboard/conventions): `r` / `w` / `p` |

### Confed (2)

| Tool | Purpose |
|---|---|
| `wb_confed_load` | Load `/etc/wb-mqtt-serial.conf`, `/etc/wb-hardware.conf` etc. with schema |
| `wb_confed_save` | Save with validation + atomic restart. Accepts `content` as object or JSON-string |

### wb-rules (5)

| Tool | Purpose |
|---|---|
| `wb_rules_list` | All rule files with enabled/disabled state |
| `wb_rules_load` | Read one rule's source |
| `wb_rules_save` | Save (JS validated by the engine, hot reload) |
| `wb_rules_disable` | Rename `<name>.js` → `<name>.js.disabled` (reversible) |
| `wb_rules_delete` | `Editor/Remove` (irreversible) |

### History (2)

| Tool | Purpose |
|---|---|
| `wb_history` | Query `db_logger/history/get_values`: points + min/max/avg per channel |
| `wb_history_chart` | Render Mermaid (default) or Vega-Lite SVG. Types: line, bar, area, point, histogram, heatmap, boxplot |

### Audit & state (3)

| Tool | Purpose |
|---|---|
| `wb_audit` | Packages, services, cron, opt/usr-local, symlinks, /mnt/data dirs, dpkg-modified files |
| `wb_state_save` | JSON snapshot to `/mnt/data/ai/wb-ai-skills/snapshots/snapshot-<ts>.json` |
| `wb_state_diff` | Compare a saved snapshot to current state |

### Modbus / wb-mqtt-serial (7)

| Tool | Purpose |
|---|---|
| `wb_modbus_templates_list` | Templates from RPC `config/Load.types`. Without `filter` — group summary; with — flat list |
| `wb_modbus_template` | One template's content (channels, parameters, groups). Views: `summary`, `full`, `channels-only`, `meta-only` |
| `wb_modbus_device_info` | Firmware parameters for a configured device (fw, model, debounce/modes/mappings) |
| `wb_modbus_probe` | Quick ping for one slave on a port |
| `wb_modbus_ports` | RS-485 port parameters from the driver config |
| `wb_modbus_scan` | Bus scan via `wb-device-manager`. Default `extended` (Fast Modbus, seconds); `standard` for third-party. Auto-detects ports and baud |
| `wb_modbus_add_devices` | Add discovered devices to wb-mqtt-serial config; copies template parameter defaults so schema validation passes (e.g. WB-MAI6 `in1_type..in6_type`). `dryRun=true` for preview |

### Diagnostics (7)

| Tool | Purpose |
|---|---|
| `wb_metrics` | Load avg, RAM, disk free for `/` and `/mnt/data` |
| `wb_logs` | `journalctl` wrapper with `since`/`until`/`grep`/`grepInvert`/`priority`/`unit`/`lines` |
| `wb_failed` | `systemctl --failed` |
| `wb_serial_debug` | Atomic enable→capture→disable cycle for `wb-mqtt-serial` debug=true; `trap`-protected |
| `wb_systemd_unit` | Manage and inspect a unit: `status`/`start`/`stop`/`restart`/`reload`/`enable`/`disable`/`mask`/`unmask`/`cat`/`list-deps` |
| `wb_network_status` | Interfaces (`ip -j`) + NetworkManager connections + default route + optional ping |
| `wb_cloud_status` | wb-cloud-agent: service activity, certificate, providers, MQTT controls |

---

## Under the hood

```
                       ┌──────────────────┐
                       │  Claude Code     │
       you ──────────► │  / opencode      │
       (chat)          │                  │
                       └────┬─────────────┘
                            │ MCP protocol (stdio)         ← only with mcp flavor
                            ▼
              ┌─────────────────────────────┐
              │  mcp-server (Bun)           │
              │  43 typed tools (Zod)       │
              │  spawns: ssh, avahi-browse  │
              │  vega-lite for SVG charts   │
              └────┬────────────────────────┘
                   │ ssh / mqtt over local network
                   ▼
              ┌─────────────────────┐
              │  Wiren Board ctrl   │
              │  stock sshd +       │
              │  stock mosquitto    │
              └─────────────────────┘
```

With **bash flavor** the LLM uses its `Bash` tool instead of `wb_*` — same flow, every shell command spelled out by the skill files.

The MCP server runs `mosquitto_sub` / `mosquitto_pub` on the controller via SSH (not locally). Locally it only spawns `ssh`/`sshpass` and `avahi-browse`.

[Model Context Protocol](https://modelcontextprotocol.io/) is a small standard for plugging tools into LLM clients. Our server uses TypeScript on Bun, no native bindings, no SQLite — only `@modelcontextprotocol/sdk`, `zod`, `vega`/`vega-lite`. State (manual-controllers list) lives in `~/.wb-mcp/controllers.json`.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WB_SSH_USER` | `root` | SSH user |
| `WB_SSH_PASSWORD` | `wirenboard` | SSH password (used if `WB_SSH_KEY` is unset) |
| `WB_SSH_KEY` | — | Path to a private key (preferred over password) |
| `WB_DISCOVERY_INTERVAL` | `15000` | mDNS scan period in ms |
| `WB_CHART_FORMAT` | — | `svg` forces `wb_history_chart` to write an SVG file under `/tmp/wb-charts/` instead of inline Mermaid. Useful for TUI clients (Claude Code CLI, opencode TUI). Unset / `mermaid` / `auto` keeps Mermaid as default for browser clients |

### Things to know

- **SSH host key.** Both flavors use `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null`. After factoryreset / FIT reflash the controller's host key changes; we don't fight it. Local-network controllers are a trusted environment.
- **Async jobs survive SSH disconnect** via `systemd-run --collect`. Long things (`apt upgrade`, full bus scan, FIT-collect) just keep running.
- **MQTT errors are typed.** `<...>/meta/error` is parsed into `{read, write, periodMiss}` per WB Conventions. When `read=true` the value topic still holds the **last-known-good** value — `wb_mqtt_inventory` shows it as such.
- **Names with spaces work.** WB-MR6C exposes controls named `Input 0`, `Input 0 counter`. We use `mosquitto_sub -F '%t\t%p'` so spaces inside names don't get clipped.
- **factoryreset is one tool call.** `wb-factoryreset --force` via `wb_ssh_exec_async` + a backup-first scenario in `/wb-controller-update`. Tested: full reset round-trip without ssh-key reload.

### Repo layout

- `mcp-server/` — TypeScript MCP server (Bun). Self-contained `src/lib/` (no npm bindings to native libs).
- `skills/bash/` — 21 skills with shell recipes. Source of truth for domain knowledge (RPC formats, Modbus quirks, wb-rules ES5 limits).
- `skills/mcp/` — 19 thin skills mapping intents to `wb_*` tools. Reference bash counterparts for deep details.
- `install-skills.sh` — installer for both flavors, both clients.
- `VERSION` — single source of truth; printed by the master skill and reported in the MCP `initialize` handshake.

---

## Troubleshooting

**`wb_discover` returns nothing.** In order of likelihood:

1. mDNS cache hasn't filled yet — first scan happens within `WB_DISCOVERY_INTERVAL` (default 15 s) of MCP server start. Wait and retry.
2. `avahi-daemon` isn't running on the host — `systemctl status avahi-daemon`, start if needed.
3. Multicast is blocked between segments — mDNS only works in one broadcast domain (no NAT, no VPN, same VLAN).
4. Controller is in WB-AP mode and host isn't on its WiFi.

Workaround: add manually — `wb_add_controller host=192.168.x.y`. Bypasses mDNS.

**SSH timeout / "handshake failure".**

1. Controller just booted (uptime < 1 min) — `sshd` is still bringing up crypto, wait 30-60 s.
2. Stale `~/.ssh/known_hosts` (bash flavor only — MCP disables host-key checking) — `ssh-keygen -R wirenboard-A25NDEMJ.local`.
3. Password changed — after factoryreset root's password is back to `wirenboard`. Custom password no longer matches.

**`bun: command not found`.** PATH issue after the install script. Either:

```bash
echo 'export BUN_INSTALL="$HOME/.bun"' >> ~/.bashrc
echo 'export PATH="$BUN_INSTALL/bin:$PATH"' >> ~/.bashrc
exec $SHELL
```

…or use the absolute path in your client config: `"command": "/home/<you>/.bun/bin/bun"`.

**MCP server doesn't appear in the client.**

1. Restart the client after editing `.mcp.json` / `~/.claude.json` / `opencode.json` — they cache MCP configs at startup.
2. Run the server directly to validate: `bun run /ABS/PATH/.../mcp-server/src/index.ts`. Should hang silently on stdio. Errors print to stderr.

**`Invalid subscription topic` from `wb_mqtt_list`.** MQTT wildcards `+` and `#` must occupy a whole level between `/`. `+` inside a name segment (`/devices/system__wb-cloud-agent__+/...`) is invalid; mosquitto rejects it.

**`apt-get update` returns 403 on a fresh-from-factory controller.** `deb.wirenboard.com` is behind a CDN that occasionally caches a stale 403 (24 h TTL). Wait it out, or `wb-release -t wb-2602` to switch to a fresher release (see <https://wirenboard.com/wiki/WB_Software_Releases>).

---

## Uninstall

```bash
# Skills (Claude Code — they're symlinks):
find ~/.claude/skills -maxdepth 1 -type l -lname '*wb-ai-skills/skills/*' -delete

# Skills (opencode — flat .md files):
ls ~/.config/opencode/agents/    # remove relevant files

# MCP server registration:
claude mcp remove wiren-board
# or hand-edit ~/.claude.json / opencode.json

# Artifacts on a controller (jobs, snapshots, backups, diag captures):
ssh root@<host> 'rm -rf /mnt/data/ai/wb-ai-skills'
```

The MCP server itself doesn't install anything global. `~/.wb-mcp/controllers.json` keeps manually added entries — small JSON, safe to delete.

---

## Requirements

- **Host:** Linux (Debian/Ubuntu tested). macOS — not tested; mDNS would need a `dns-sd` shim instead of `avahi-browse`. Windows — no.
- **Client:** Claude Code CLI or opencode.
- **Controllers:** anything reachable over SSH on stock firmware. Tested on wb7 (wb-2410, wb-2602) and wb8 (wb-2507).

## License

MIT — see [LICENSE](LICENSE).

## Related

- [`wb-ai-helper-desktop`](https://github.com/wirenboard/wb-ai-helper-desktop) — sibling project: a standalone desktop chat with its own DB and UI, talks to controllers over SSH/MQTT, encapsulates Anthropic / OpenAI / AITunnel APIs. Different deployment model: there you bring your API key; here you bring your existing Claude Code or opencode setup.
- [Wiren Board MQTT Conventions](https://github.com/wirenboard/conventions) — the spec these tools speak.
