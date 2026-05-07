# wb-ai-skills

**Talk to your [Wiren Board](https://wirenboard.com) controllers from an AI assistant.**
Drop the chat box into [Claude Code](https://claude.ai/code) or [opencode](https://opencode.ai),
type a question or a request — the assistant figures out which controller, runs SSH/MQTT/Modbus
commands, reads logs, edits configs, and reports back.

```
> /wiren-board
> something is wrong on A25NDEMJ — find out what

→ wb_failed → fstrim.service is failing
→ wb_logs unit=fstrim → status=64/USAGE, /mnt/sdcard not mounted
→ explanation in plain English + suggested override-conf to fix it
```

```
> scan the bus on A25NDEMJ and add everything you find to the config

→ wb_modbus_scan → 8 devices on /dev/ttyRS485-1 (Fast Modbus)
→ wb_modbus_add_devices dryRun=true → preview the change
→ wait for confirmation → write /etc/wb-mqtt-serial.conf
→ wb_mqtt_inventory → all 8 devices appear in MQTT, polling, no errors
```

No new desktop app. No vendor lock-in. The assistant you already use, plus a typed
toolbox for WB plus skill files telling it *how* to use them well.

---

## What you get

| | |
|---|---|
| 🧰 **MCP server** | Bun-based service exposing **43 typed tools** (`wb_discover`, `wb_ssh_exec`, `wb_mqtt_rpc`, `wb_modbus_scan`, `wb_history_chart`, `wb_systemd_unit`, ...). The LLM calls them directly through the [Model Context Protocol](https://modelcontextprotocol.io). Structured input/output, type checking, no shell-quoting accidents. |
| 📚 **Skill packs** | **21 bash skills** (no MCP needed) and **19 mcp skills** (route intents to the typed tools). Domain knowledge: how to enable a Modbus channel, when `port/Scan` lies, what `meta/error` flags mean per [WB Conventions](https://github.com/wirenboard/conventions), how to write a wb-rules JS rule, how to back up before factoryreset, ... |
| 🔌 **Pure-client** | Nothing runs **on** the controller. SSH + stock `mosquitto` + `avahi` is all the controller needs. Survives factoryreset and FIT firmware reflash without ssh-key churn. |

---

## What you can ask

A fresh assistant session, after loading the master skill `/wiren-board`, can do all of this without further hand-holding:

- **Discovery & status:** "find all WB controllers in the LAN", "what firmware does A25NDEMJ run?", "show me load and disk on every controller"
- **Diagnostics:** "why is wb-mqtt-serial unhappy on A25NDEMJ?", "any failed services?", "errors in the journal in the last hour"
- **Modbus:** "scan the bus, list devices", "WB-MAI6 has channels in1..in6 — turn them all on", "show me the WB-MR6C template"
- **MQTT:** "what's the value of `/devices/wb-mr6c_2/controls/K1`?", "publish ON to `K1/on`", "list every device with its controls"
- **Rules & scenarios:** "make a rule: when motion sensor fires, turn on the light for 60 seconds", "create a thermostat scenario for the living room"
- **History:** "plot CPU temperature for the last 24 hours as SVG", "average current draw last week"
- **Backup & update:** "make a full backup before I do `apt upgrade`", "what packages will be upgraded?", "factoryreset this test controller"
- **Network & cloud:** "is internet working?", "switch the uplink to sim2", "is wb-cloud-agent connected?"

Each of those is one sentence to the LLM. The LLM picks tools, runs them, reads outputs, asks for confirmation on destructive ops, and reports.

---

## Two flavors — pick **one**

| | bash skills only | bash skills + MCP server |
|---|---|---|
| **What runs** | LLM calls `Bash` and runs `ssh root@<host>` / `mosquitto_*` directly | LLM calls typed `wb_*` tools; the MCP server runs them and returns structured JSON |
| **Setup** | Just SSH access + a few CLI utilities on the host | Same + Bun 1.3+ + a `.mcp.json` config |
| **Quoting / errors** | LLM constructs shell strings — occasionally trips on quotes | Server validates input via Zod, returns typed errors |
| **Discovery** | LLM runs `avahi-browse` itself | `wb_discover` keeps a 15-second mDNS cache, merges manual entries |
| **History charts** | LLM emits Mermaid or asks for python | `wb_history_chart` returns a Vega-Lite SVG ready to view |
| **Surface** | 21 skills | Same 21 skills (mcp-flavor variants) + 43 tools |

The skill files share the same `name:`, so **install only one of the two flavors** — Claude Code / opencode would otherwise pick whichever loads first.

`skills/bash/` is the **source of domain knowledge** (RPC formats, Modbus quirks, wb-rules ES5 limits). `skills/mcp/` variants are thin and reference bash for deep details.

---

## Quick start

### Bash flavor (5 minutes, no Bun)

```bash
sudo apt install avahi-utils mosquitto-clients sshpass jq

git clone https://github.com/wirenboard/wb-ai-skills.git
cd wb-ai-skills

./install-skills.sh bash claude --global       # for Claude Code
# or
./install-skills.sh bash opencode --global     # for opencode
```

In Claude Code:

```
> /wiren-board
> find controllers in the network and show their firmware versions
```

### MCP flavor (10 minutes, with Bun)

```bash
sudo apt install avahi-utils mosquitto-clients sshpass jq
curl -fsSL https://bun.sh/install | bash

git clone https://github.com/wirenboard/wb-ai-skills.git
cd wb-ai-skills/mcp-server && bun install && cd ..

./install-skills.sh mcp claude --global
```

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "wiren-board": {
      "command": "bun",
      "args": ["run", "/ABS/PATH/TO/wb-ai-skills/mcp-server/src/index.ts"],
      "env": { "WB_SSH_USER": "root", "WB_SSH_PASSWORD": "wirenboard", "WB_CHART_FORMAT": "svg" }
    }
  }
}
```

Restart Claude Code. Then:

```
> /wiren-board
> wb_discover then wb_probe each one
```

Detailed setup, opencode config, troubleshooting — see [INSTALL.md](INSTALL.md).

---

## Skills (21 bash + 19 mcp)

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
| `wb-history` | ✓ | ✓ | Query wb-mqtt-db, render SVG charts |
| `wb-bugreport` | ✓ | ✓ | Compose a bug report for support, gather diag archive |
| `wb-diagrams` | ✓ | — | Mermaid diagrams of automation logic |
| `wb-documentation-search` | ✓ | — | Search wirenboard.com/wiki and GitHub |

`wb-diagrams` and `wb-documentation-search` are controller-independent — the installer always pulls them from `skills/bash/` even when you choose mcp-flavor.

---

## MCP tools (43 across 11 groups)

Full table with parameters in [`mcp-server/README.md`](mcp-server/README.md). Brief map:

- **Discovery:** `wb_discover`, `wb_probe`, `wb_add_controller`
- **SSH & files:** `wb_ssh_exec`, `wb_ssh_exec_async`, `wb_read_file`, `wb_write_file`
- **Async jobs:** `wb_job_status`, `wb_job_tail`, `wb_job_cancel` — survive SSH disconnect
- **MQTT:** `wb_mqtt_read`, `wb_mqtt_write` (with `retain`/`qos`), `wb_mqtt_list`, `wb_mqtt_rpc`
- **Devices:** `wb_mqtt_devices`, `wb_mqtt_controls`, **`wb_mqtt_inventory`** (combined view, error flags per [WB Conventions](https://github.com/wirenboard/conventions))
- **Confed:** `wb_confed_load`, `wb_confed_save` (JSON validation + atomic restart)
- **wb-rules:** `wb_rules_list`, `wb_rules_load`, `wb_rules_save`, `wb_rules_disable`, `wb_rules_delete`
- **History:** `wb_history`, `wb_history_chart` (Vega-Lite SVG)
- **Audit/state:** `wb_audit`, `wb_state_save`, `wb_state_diff`
- **Modbus/serial:** `wb_modbus_template`, `wb_modbus_templates_list`, `wb_modbus_device_info`, `wb_modbus_probe`, `wb_modbus_ports`, **`wb_modbus_scan`** (via `wb-device-manager`), **`wb_modbus_add_devices`**
- **Diagnostics:** `wb_metrics`, `wb_logs` (with `since`/`grep`), `wb_failed`, `wb_serial_debug`, `wb_systemd_unit`, `wb_network_status`, `wb_cloud_status`

---

## How it works

```
                       ┌──────────────────┐
                       │  Claude Code     │
       you ──────────► │  / opencode      │
       (chat)          │                  │
                       └────┬─────────────┘
                            │ MCP protocol (stdio)
                            ▼
              ┌─────────────────────────────┐
              │  mcp-server (Bun)           │
              │  43 typed tools (Zod)       │
              │  ssh / mosquitto / avahi    │
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

If MCP isn't installed, the LLM uses bash skills directly: same flow, just `Bash` instead of `wb_*` tools — every shell command spelled out by the skill files.

### What's MCP?

[Model Context Protocol](https://modelcontextprotocol.io/) — a small standard for plugging tools into LLM clients. Each tool has a name, a JSON-Schema for input, and returns structured output. The LLM picks one, fills params, gets the result. Works with Claude Code, opencode, and any other MCP-aware client.

This repo's MCP server is implemented in TypeScript on Bun, no native bindings, no SQLite — only `@modelcontextprotocol/sdk`, `zod`, `vega`/`vega-lite`. State (the manual-controllers list) lives in `~/.wb-mcp/controllers.json`.

---

## Things you should know

- **SSH host key.** The MCP server uses `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null`. After factoryreset / FIT reflash the controller's host key changes; we don't fight it. A controller in your local network is a trusted environment.
- **Async jobs** survive SSH disconnect via `systemd-run --collect`. Long things (`apt upgrade`, full bus scan, FIT-collect) just keep running. The script and log live in `/mnt/data/ai/wb-ai-skills/jobs/<id>.{sh,log}`, garbage-collected after 24 hours.
- **MQTT errors are typed.** `<...>/meta/error` is parsed into `{read, write, periodMiss}` per WB Conventions. When `read=true` the value topic still holds the **last-known-good** value — `wb_mqtt_inventory` shows it as such.
- **Names with spaces work.** WB-MR6C exposes controls named `Input 0`, `Input 0 counter`. We use `mosquitto_sub -F '%t\t%p'` (TAB separator) so spaces inside names don't get clipped.
- **factoryreset is one tool call.** `wb-factoryreset --force` via `wb_ssh_exec_async` + a sane backup-first scenario in `/wb-controller-update`. Tested in CI: full reset round-trip without ssh-key reload.

---

## Requirements

- **Host machine:** Linux (Debian/Ubuntu tested). macOS — not tested; mDNS would need a `dns-sd` shim instead of `avahi-browse`. Windows — no.
- **For the bash flavor:** `avahi-utils`, `mosquitto-clients`, `sshpass` (or pre-deployed SSH key), `jq`.
- **For the MCP flavor:** all of the above + Bun 1.3+.
- **Client:** Claude Code CLI or opencode.
- **Controllers:** anything reachable over SSH on stock firmware. Tested on wb7 (wb-2410, wb-2602) and wb8 (wb-2507).

---

## License

MIT — see [LICENSE](LICENSE).

## Related

- [`wb-ai-helper-desktop`](https://github.com/wirenboard/wb-ai-helper-desktop) — sibling project: a standalone desktop chat with its own DB and UI, talks to controllers over SSH/MQTT, encapsulates Anthropic / OpenAI / AITunnel APIs. Different deployment model: there you bring your API key; here you bring your existing Claude Code or opencode setup.
- [Wiren Board MQTT Conventions](https://github.com/wirenboard/conventions) — the spec these tools speak.
