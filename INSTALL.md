# Installing wb-ai-skills

Two independent setups. **Pick one.** Don't install both — bash and mcp skills share the same `name:` in their frontmatter, the LLM client would only see one of each anyway.

| | bash flavor | mcp flavor |
|---|---|---|
| **What you need on the host** | SSH + a few CLI utils | Same + [Bun](https://bun.sh) 1.3+ |
| **What you need on the controller** | Stock SSH + mosquitto (already there) | Same |
| **What the LLM uses** | `Bash` tool only | `wb_*` typed tools through MCP |
| **Setup time** | 5 min | 10 min |
| **Best for** | Simple test, no Bun, fully scripted recipes | Daily driver — typed errors, structured outputs, ready-made charts |

---

## Bash flavor

### 1. Install host CLI tools

```bash
sudo apt install avahi-utils mosquitto-clients sshpass jq
```

What each is for:

- `avahi-utils` — `avahi-browse` for mDNS discovery (`wirenboard-<SN>.local`).
- `mosquitto-clients` — `mosquitto_sub` / `mosquitto_pub` for MQTT (the bash skills run them via SSH inside the controller, but having them on the host is sometimes useful for ad-hoc debugging).
- `sshpass` — only if you use the default password (`wirenboard`). With an SSH key — not needed.
- `jq` — every bash skill uses it for JSON parsing.

### 2. Clone and install skills

```bash
git clone https://github.com/wirenboard/wb-ai-skills.git
cd wb-ai-skills

# Claude Code (system-wide):
./install-skills.sh bash claude --global
#   → ~/.claude/skills/ (symlinks)

# Or per-project:
./install-skills.sh bash claude
#   → ./.claude/skills/

# opencode:
./install-skills.sh bash opencode --global
#   → ~/.config/opencode/agents/ (flat .md, frontmatter rewritten)
```

Symlinks are used for Claude Code so edits in the repo reflect immediately. opencode wants flat `.md` files with `mode: primary`, the script generates them.

### 3. Set up SSH access to controllers

Default factory creds: `root` / `wirenboard`. Either use `sshpass` (set `WB_SSH_PASSWORD` env or rely on the default), or push a key — recommended:

```bash
ssh-copy-id -o StrictHostKeyChecking=accept-new root@wirenboard-A25NDEMJ.local
```

After factoryreset the host key changes and the password is reset to `wirenboard` — the bash skills handle this by passing `-o StrictHostKeyChecking=accept-new` already.

### 4. Verify

In Claude Code:

```
> /wiren-board
> find every controller in the network and show release + uptime
```

Expected: a list with `sn`, `host`, `release`, `uptime`. If empty — see [common issues](#common-issues).

In opencode:

```
> @wiren-board find controllers and show release + uptime
```

---

## MCP flavor

### 1. Install host CLI tools and Bun

```bash
sudo apt install avahi-utils mosquitto-clients sshpass jq
curl -fsSL https://bun.sh/install | bash
# → installs to ~/.bun, adds it to your shell config
exec $SHELL    # reload PATH
bun --version  # should print 1.3.x or newer
```

### 2. Clone and bootstrap

```bash
git clone https://github.com/wirenboard/wb-ai-skills.git
cd wb-ai-skills/mcp-server
bun install                  # ~30 seconds, no compile step
```

No build — Bun runs TypeScript directly (`noEmit: true` in `tsconfig.json`).

### 3. Install MCP skills

```bash
cd ..   # back to repo root
./install-skills.sh mcp claude --global       # or opencode --global, or no --global for per-project
```

The installer for the mcp flavor also pulls in two controller-independent skills from the bash set: `wb-diagrams` (Mermaid) and `wb-documentation-search` (wiki / GitHub). 21 files total in `~/.claude/skills/` or `~/.config/opencode/agents/`.

### 4. Connect the MCP server

#### Claude Code

`~/.claude.json` (system-wide) or `<project>/.mcp.json` (per-project):

```json
{
  "mcpServers": {
    "wiren-board": {
      "command": "bun",
      "args": ["run", "/ABS/PATH/TO/wb-ai-skills/mcp-server/src/index.ts"],
      "env": {
        "WB_SSH_USER": "root",
        "WB_SSH_PASSWORD": "wirenboard"
      }
    }
  }
}
```

Restart Claude Code so it re-reads the config. Or one-line equivalent:

```bash
claude mcp add wiren-board -- bun run /ABS/PATH/TO/wb-ai-skills/mcp-server/src/index.ts
```

#### opencode

`~/.config/opencode/opencode.json` (global) or `./opencode.json` (per-project):

```json
{
  "mcp": {
    "wiren-board": {
      "type": "local",
      "command": ["bun", "run", "/ABS/PATH/TO/wb-ai-skills/mcp-server/src/index.ts"],
      "environment": {
        "WB_SSH_USER": "root",
        "WB_SSH_PASSWORD": "wirenboard"
      },
      "enabled": true
    }
  }
}
```

Note the differences vs Claude Code:
- top-level key is `mcp`, not `mcpServers`;
- `command` is an array `[cmd, ...args]`, not separate `command` + `args`;
- env is `environment`, not `env`.

### 5. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WB_SSH_USER` | `root` | SSH user |
| `WB_SSH_PASSWORD` | `wirenboard` | SSH password (used if no key) |
| `WB_SSH_KEY` | — | Path to a private key (preferred over password) |
| `WB_DISCOVERY_INTERVAL` | `15000` | mDNS scan period in ms |
| `WB_CHART_FORMAT` | — | `svg` forces `wb_history_chart` to write an SVG file (auto path under `/tmp/wb-charts/`) instead of emitting Mermaid. Useful for TUI clients that don't render Mermaid (Claude Code CLI, opencode TUI). Unset / `mermaid` / `auto` keep the default Mermaid output for browser clients. |

### 6. Verify

After Claude Code restart:

```
> /wiren-board
> wb_discover, then wb_probe each controller it finds
```

Expected output: a list of controllers, then per-controller `uname` / `release` / `fwVersion` / `uptime`.

If the LLM doesn't see `wb_*` tools — the MCP server didn't start. Check:

```bash
bun run /ABS/PATH/TO/wb-ai-skills/mcp-server/src/index.ts
```

Should hang silently waiting for stdio. Errors print to stderr — that's the diagnostic signal.

---

## Common issues

### `wb_discover` returns nothing

In order of likelihood:

1. **mDNS cache hasn't filled yet.** First scan happens within `WB_DISCOVERY_INTERVAL` (default 15 s) of MCP server start. Wait 15 s and retry.
2. **`avahi-daemon` isn't running on the host.** `systemctl status avahi-daemon` — start it if needed.
3. **Multicast is blocked between segments.** mDNS only works in one broadcast domain. If your controller is across NAT / VPN / different VLAN — it won't be visible.
4. **Controller is in WB-AP mode** (its own WiFi access point) and your host isn't connected to that WiFi.

Workaround: add by IP manually — `wb_add_controller host=192.168.x.y`. Bypasses mDNS entirely.

### SSH timeout / "handshake failure"

1. **Controller just booted** (uptime < 1 min). `sshd` is still bringing up crypto. Wait 30-60 s.
2. **Stale `~/.ssh/known_hosts` entry** (only relevant for bash flavor — MCP disables host-key checking). After factoryreset the host key changes:
   ```bash
   ssh-keygen -R wirenboard-A25NDEMJ.local
   ```
3. **Password changed.** After factoryreset root's password is back to `wirenboard`. If you had something custom — `WB_SSH_PASSWORD` no longer matches.

### `bun: command not found`

PATH issue. After `curl ... bun.sh/install | bash`:

```bash
echo 'export BUN_INSTALL="$HOME/.bun"' >> ~/.bashrc
echo 'export PATH="$BUN_INSTALL/bin:$PATH"' >> ~/.bashrc
exec $SHELL
```

Or use the absolute path in `.mcp.json`: `"command": "/home/<you>/.bun/bin/bun"`.

### MCP server doesn't appear in Claude Code

1. **Restart Claude Code** after editing `.mcp.json` or `~/.claude.json` — it caches MCP configs at startup.
2. **Check Claude Code logs** (`/help` shows the diagnostics path). Errors from `bun` show up there.
3. **Run the server directly to validate:**
   ```bash
   bun run /ABS/PATH/TO/wb-ai-skills/mcp-server/src/index.ts
   ```
   Should hang silently. Any output to stderr is the error.

### `Invalid subscription topic` from `wb_mqtt_list`

MQTT wildcards `+` and `#` must occupy a **whole level** between `/`. Examples:

- ✅ `/devices/+/controls/+`
- ✅ `/devices/wb-mr6c_2/#`
- ❌ `/devices/system__wb-cloud-agent__+/controls/+` — `+` inside a name segment is invalid; mosquitto rejects it.

### `apt-get update` returns 403 on a fresh-from-factory controller

`deb.wirenboard.com` is behind a CDN that occasionally caches a stale 403 for some edges. The TTL is 24 h. Workarounds:

- Wait for the cache to expire.
- Switch to a newer release: `wb-release -t wb-2602` (or whatever's current — see <https://wirenboard.com/wiki/WB_Software_Releases>).
- Force HTTPS in `/etc/apt/sources.list.d/wirenboard.list` (sometimes only HTTP is poisoned).

---

## Uninstall

### Skills

```bash
# Claude Code (skills are symlinks):
unlink ~/.claude/skills/wiren-board    # one at a time
# or remove all wb-ai-skills symlinks at once:
find ~/.claude/skills -maxdepth 1 -type l -lname '*wb-ai-skills/skills/*' -delete

# opencode (flat .md files):
rm ~/.config/opencode/agents/wiren-board.md     # one at a time
```

### MCP server

```bash
claude mcp remove wiren-board
# or hand-edit ~/.claude.json / .mcp.json
```

The server itself doesn't install anything global — Bun is per-user, and `~/.wb-mcp/controllers.json` stores manually added controllers (small JSON, safe to keep or `rm`).

### Artifacts on controllers

Skills write under `/mnt/data/ai/wb-ai-skills/`: backups, snapshots, async-job logs, diag captures. None of it is required by the controller; cleanup if you want:

```bash
ssh root@<host> 'rm -rf /mnt/data/ai/wb-ai-skills'
```

This survives factoryreset (it's user data on `/mnt/data`); only a FIT firmware reflash wipes it.
