# Installing wb-ai-integration

Two independent installation paths. Pick **one**:

| Variant | When | What's needed |
|---|---|---|
| **bash-only** | Minimal setup, no Bun, don't want to set up MCP | Only SSH + `mosquitto_*` + `avahi-browse` + `jq` |
| **mcp-flavor** | Want typed tools, ready to install Bun | Bun 1.3+, MCP server running via `.mcp.json` |

**Don't install both at once** — `bash` and `mcp` skills share the same `name:` in frontmatter, Claude Code/opencode will pick whichever.

---

## bash-only setup

### 1. Dependencies on the host machine

Linux:

```bash
sudo apt install avahi-utils mosquitto-clients sshpass jq
```

- `avahi-utils` — `avahi-browse` for mDNS controller discovery.
- `mosquitto-clients` — `mosquitto_sub`/`mosquitto_pub` for MQTT via SSH tunnel to the controller's broker.
- `sshpass` — if using a password (`wirenboard` by default). Not needed if SSH key is deployed.
- `jq` — for bash skills with JSON parsing.

### 2. Cloning and installing skills

```bash
git clone https://github.com/wirenboard/wb-ai-integration.git wb-ai-integration
cd wb-ai-integration

# Globally for Claude Code:
./install-skills.sh bash claude --global
# → into ~/.claude/skills/

# Per-project (only in current directory):
./install-skills.sh bash claude
# → into ./.claude/skills/

# For opencode:
./install-skills.sh bash opencode --global
# → into ~/.config/opencode/agents/
```

The script installs skills as symlinks for Claude Code (fresh edits visible immediately), and as flat `.md` files for opencode (with frontmatter conversion).

### 3. SSH access to controllers

WB controller defaults:
- **Login**: `root`
- **Password**: `wirenboard` (factory)
- **Host**: `wirenboard-<SN>.local` (via mDNS) or direct IP.

**Recommended to deploy an SSH key** (avoids password and `sshpass`):

```bash
ssh-copy-id -o StrictHostKeyChecking=accept-new root@wirenboard-A25NDEMJ.local
```

After that SSH works without a password.

### 4. Verification

In Claude Code:

```
> /wiren-board
> find all controllers on the network
```

The skill should run `avahi-browse -arp _workstation._tcp` and show the list.

---

## MCP-flavor setup

### 1. Dependencies

Same as for bash-flavor (`avahi-utils`, `mosquitto-clients`, `sshpass`, `jq`) **plus**:

- **Bun 1.3+** — runtime for the MCP server ([bun.sh](https://bun.sh)).

```bash
curl -fsSL https://bun.sh/install | bash
```

### 2. Installing the MCP server

```bash
git clone https://github.com/wirenboard/wb-ai-integration.git wb-ai-integration
cd wb-ai-integration/mcp-server
bun install
```

No build step — Bun executes TypeScript directly. `noEmit: true` in `tsconfig.json`.

### 3. Installing MCP skills

```bash
cd ..
./install-skills.sh mcp claude --global
# or
./install-skills.sh mcp opencode --global
```

### 4. Connecting the MCP server to Claude Code

In `~/.claude.json` (global) or `.mcp.json` (in project):

```json
{
  "mcpServers": {
    "wiren-board": {
      "command": "bun",
      "args": ["run", "/ABS/PATH/wb-ai-integration/mcp-server/src/index.ts"],
      "env": {
        "WB_SSH_USER": "root",
        "WB_SSH_PASSWORD": "wirenboard"
      }
    }
  }
}
```

Or in one command:

```bash
claude mcp add wiren-board -- bun run /ABS/PATH/wb-ai-integration/mcp-server/src/index.ts
```

### 5. Connecting the MCP server to opencode

In `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "wiren-board": {
      "type": "local",
      "command": ["bun", "run", "/ABS/PATH/wb-ai-integration/mcp-server/src/index.ts"],
      "environment": {
        "WB_SSH_USER": "root",
        "WB_SSH_PASSWORD": "wirenboard"
      },
      "enabled": true
    }
  }
}
```

Differences from Claude Code:
- top-level key is `mcp`, not `mcpServers`;
- `command` is an array `[cmd, ...args]`, not a string + `args`;
- env is `environment`, not `env`.

### 6. Environment variables

| Variable | Default | Purpose |
|------------|---------|------------|
| `WB_SSH_USER` | `root` | SSH login |
| `WB_SSH_PASSWORD` | `wirenboard` | SSH password (if no key) |
| `WB_SSH_KEY` | — | path to private key (instead of password) |
| `WB_DISCOVERY_INTERVAL` | `15000` | mDNS scan period (ms) |

### 7. Verification

In Claude Code (after restart, so `.mcp.json` gets picked up):

```
> /wiren-board
> find controllers via wb_discover
```

Records with `sn`, `host`, `addresses`, `reachable: true` should appear.

```
> wb_probe sn=A25NDEMJ
```

Returns `uname`, `release`, `fwVersion`.

---

## Common issues

### `wb_discover` finds nothing

**Causes and checks** (in decreasing order of likelihood):

1. **mDNS cache is still empty.** First run of the MCP server — discovery polls the network every 15 sec. Wait ~15 sec after start and retry.
2. **`avahi-daemon` is not running on the host.** Linux: `systemctl status avahi-daemon`. Start it if it's off.
3. **Multicast blocked between segments.** mDNS only works within one broadcast domain. If the controller is behind NAT/VPN/in another VLAN — won't see it.
4. **WB-AP mode.** If the controller is in access point mode (`wb-ap`) and the host isn't connected to it via WiFi — invisible.

**Workaround:** `wb_add_controller host=192.168.x.y` — manual addition by IP, bypassing mDNS.

### SSH timeout / handshake failure

1. **Controller just booted** (uptime < 1 min) — sshd is still initializing crypto. Wait 30-60 sec and retry.
2. **`StrictHostKeyChecking` is blocking** (although ours is off) — if you use bash-flavor with system `ssh`, fix `~/.ssh/known_hosts`: `ssh-keygen -R wirenboard-A25NDEMJ.local`. After factory reset the host-key changes.
3. **Password changed** — after `factoryreset` the root password reverts to `wirenboard`. If you set your own before — the previous WB_SSH_PASSWORD won't work anymore.

### `bun: command not found`

Bun is not in `PATH`. After install:

```bash
echo 'export BUN_INSTALL="$HOME/.bun"' >> ~/.bashrc
echo 'export PATH="$BUN_INSTALL/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Or specify the full path in `.mcp.json`: `"command": "/home/<user>/.bun/bin/bun"`.

### MCP server isn't picked up by Claude Code

1. Restart Claude Code after editing `.mcp.json` / `~/.claude.json`.
2. Check the logs: Claude Code writes MCP startup errors to its log (`/help` → diagnostics section).
3. Test by hand: `bun run /ABS/PATH/wb-ai-integration/mcp-server/src/index.ts` — should output nothing (stdio transport waits for messages); if it outputs an error — that's the problem.

### `Invalid subscription topic` in `wb_mqtt_list`

In MQTT, wildcards `+`/`#` occupy **the entire level between `/`**, not part of a name. Invalid example: `/devices/system__wb-cloud-agent__+/...` (`+` inside a level).

Correct: `/devices/+/controls/+` or `/devices/<exact_name>/#`.

### Controller doesn't update via apt

After factoryreset on old firmware (e.g. wb-2410) the `deb.wirenboard.com` repository may temporarily return **403** (CDN cache). Check:

```bash
ssh root@<host> 'curl -sI http://deb.wirenboard.com/wb7/bullseye/dists/stable/InRelease | head -3'
```

If 403 — wait 24 hours (CDN TTL) or use `wb-release -t <fresh-release>` to switch the repository.

---

## Uninstalling

### Bash/MCP skills

Delete the created files/symlinks in the directory that `install-skills.sh` prints at the end.

```bash
# Claude Code (global) — install-skills.sh places symlinks to directories:
unlink ~/.claude/skills/wiren-board   # each by name
# or in bulk:
find ~/.claude/skills -maxdepth 1 -type l -lname '*wb-ai-integration/skills/*' -delete

# opencode (global) — these are flat .md files:
rm ~/.config/opencode/agents/wiren-board.md   # each by name
```

### MCP server

```bash
# Claude Code
claude mcp remove wiren-board

# or manually: remove the block from ~/.claude.json / .mcp.json

# The server itself leaves nothing on the host — Bun doesn't install global binaries.
# Delete the project clone:
rm -rf wb-ai-integration
```

### Artifacts on controllers

Skills write to `/mnt/data/ai/wb-ai-integration/` (snapshots, jobs, diag, backups). Not critical — survives factoryreset and doesn't interfere with operation. Manual cleanup if you want:

```bash
ssh root@<host> 'rm -rf /mnt/data/ai/wb-ai-integration'
```
