# wb-ai-skills

[![CI](https://github.com/wirenboard/wb-ai-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/wirenboard/wb-ai-skills/actions/workflows/ci.yml)

Two things in one repository, both built to help AI coding agents work with a [Wiren Board](https://wirenboard.com) controller:

1. **`wb-plc` plugin** — methodology skills for AI agents that drive a controller over SSH. Distributed as a Claude Code / GitHub Copilot CLI plugin and as plain markdown for any other agent. See [Skills](#skills) below.
2. **`wb-cli` package** — Debian package installed *on* the controller. CLI with a stable JSON envelope contract, built so an agent can SSH in and call `wb-cli --json <command>` to get structured output. See [wb-cli](#wb-cli) below.

The two are independent: you can use the skills without the controller package, and vice versa.

---

## Skills

The `wb-plc/skills/` directory holds nine skills covering everything a remote agent needs to operate a WB controller: discovery, troubleshooting, network, MQTT, Modbus, automation rules, Zigbee, backup/restore, and writing custom software for the controller.

| Skill | What it covers |
|---|---|
| `wiren-board` | Master entry: mDNS discovery, SSH conventions, `wb-cli` usage. **Load first.** |
| `wb-troubleshooting` | Failed systemd units, disk, kernel/firmware mismatch, Docker, diagnostic archive. |
| `wb-serial` | RS-485 / Modbus — custom templates, device configuration, bus diagnostics (CRC, timeouts). |
| `wb-rules` | wb-rules JavaScript automation (ES5, virtual devices, cron, sensors). |
| `wb-mqtt-broker` | Mosquitto MQTT broker — auth, ACLs, TLS, external bridges. |
| `wb-network` | Ethernet, WiFi, 4G, OpenVPN, failover, DNS, hotspot. |
| `wb-zigbee` | Zigbee via zigbee2mqtt (pairing, OTA, native vs Docker). |
| `wb-controller-backup` | Full controller backup and restore. |
| `wb-dev` | Writing software for WB — daemons, MQTT bridges, MQTT-RPC, cross-compilation, Debian packaging. |

### Install for Claude Code or GitHub Copilot CLI (recommended)

Both agents read the same plugin manifest. One command to register the marketplace, one to install the plugin:

```
/plugin marketplace add wirenboard/wb-ai-skills
/plugin install wb-plc@wb-ai-skills
```

Updates: `/plugin marketplace update wb-ai-skills` then `/plugin update wb-plc@wb-ai-skills`.

### Install for OpenCode, older Claude Code, or other agents

Use `install-skills.sh` — it materializes the skills into the format each agent expects.

```bash
# Claude Code (skill format — directory with SKILL.md + side files)
./install-skills.sh claude              # → ./.claude/skills/   (project-local)
./install-skills.sh claude --global     # → ~/.claude/skills/   (user-wide)

# OpenCode (flat .md per agent, frontmatter rewritten: allowed-tools → mode: primary)
./install-skills.sh opencode            # → ./.opencode/agents/
./install-skills.sh opencode --global   # → ~/.config/opencode/agents/

# Any other agent (frontmatter trimmed to name + description)
./install-skills.sh manual --dest /path/to/agent/prompts

# Uninstall
./install-skills.sh uninstall claude --global
```

`./install-skills.sh --help` lists all flags and defaults.

### Install on Windows

PowerShell — copy the skill directories from `wb-plc/skills/` to the agent's skills folder.

| Agent | Destination |
|---|---|
| Claude Code (user-wide) | `%USERPROFILE%\.claude\skills\` |
| Claude Code (project) | `.claude\skills\` inside the project |
| OpenCode (user-wide) | `%APPDATA%\opencode\agents\` (flatten — extract SKILL.md as `<name>.md`, rewrite `allowed-tools:` to `mode: primary`) |

### Install on the controller

The `wb-cli` `.deb` also drops the skill markdowns into `/usr/share/wb-cli/skills/` so an agent that SSH'd in can read them locally.

---

## wb-cli

Command-line tool that runs **on the controller**, exposing controller state and operations through a stable JSON contract.

```bash
ssh root@wirenboard-A25NDEMJ wb-cli info
# serial_number   A25NDEMJ
# release_name    wb-2602
# hostname        wirenboard-A25NDEMJ
# uptime_seconds  407130.59

ssh root@wirenboard-A25NDEMJ wb-cli --json info
# → {"data": {"serial_number": "A25NDEMJ", "release_name": "wb-2602", ...}}

ssh root@wirenboard-A25NDEMJ wb-cli --json dev wb-mr6c_2/K1 1
# → {"data": {"device": "wb-mr6c_2", "control": "K1", "value": "1", "ok": true}}
```

### Commands

| Plugin | What it covers |
|---|---|
| `info` | Controller identity: serial number, firmware release, board revision, hostname, uptime |
| `audit` | Quick health check (failed units + identity) |
| `cloud` | Wiren Board cloud-agent status |
| `dev` | Devices and controls — list, read, write through the wb-rules `<device>/<control>` form |
| `mqtt` | Raw MQTT: read retained, write, list, live subscribe |
| `mqtt-debug` | Verbose mosquitto PUBLISH tracing |
| `confed` | Read and write service config files through wb-mqtt-confed |
| `rules` | Manage wb-rules automation scripts |
| `history` | Time-series data from wb-mqtt-db (raw rows) |
| `serial` | RS-485 / Modbus operations (incl. `wb-fw` firmware update) |
| `serial-debug` | RS-485 driver debug capture |
| `snapshot` | Capture and diff small JSON snapshots of controller state |
| `job` | Long-running commands as transient systemd units |
| `plugins` | Self-introspection: which commands this wb-cli build knows about |

Each plugin has its own `--help`:

```bash
wb-cli --help                    # top-level — all plugins
wb-cli <plugin> --help           # subcommands of one plugin
wb-cli <plugin> <action> --help  # flags for one action
```

### Output modes

`wb-cli` emits **human-friendly** output (tables / key-value lines) by default everywhere — including pipes and SSH without a TTY. JSON is opt-in via `--json` or `WB_CLI_OUTPUT=json`. A stderr spinner / progress bar is drawn for long-running calls only when stderr is a TTY, so JSON to stdout always stays clean.

```bash
wb-cli --json dev               # force JSON (LLM agents / scripts)
WB_CLI_OUTPUT=json wb-cli info  # same via env
WB_CLI_NO_SPINNER=1 wb-cli ...  # silence the spinner regardless of mode
```

The JSON envelope is the stable, machine-readable contract:

- **Success:** `{"data": { ... }}` — `snake_case` keys, arrays are always arrays.
- **Error:** `{"error": {"code": "SCREAMING_SNAKE", "message": "...", "hint": "...", "details": { ... }}}`.

Exit codes: **0** success · **1** domain error · **2** usage · **3** environment · **130** SIGINT. Error codes are stable across releases.

### Install on a controller

Once `wb-cli` is published to the Wiren Board apt repository:

```bash
apt-get update && apt-get install -y wb-cli
```

Until then, install the latest `.deb` from [GitHub Releases](https://github.com/wirenboard/wb-ai-skills/releases/latest):

```bash
URL=$(curl -fsSL https://api.github.com/repos/wirenboard/wb-ai-skills/releases/latest \
      | grep -oE 'https://[^"]+wb-cli_[^"]+\.deb' | head -1)
curl -fsSL -o /tmp/wb-cli.deb "$URL"
apt-get install -y /tmp/wb-cli.deb     # resolves python3-mqttrpc / python3-wb-common from the wirenboard repo
```

The `.deb` is `Architecture: all` and works on any wb6/wb7 running Debian ≥ bullseye.

---

## Architecture

```
.claude-plugin/
  marketplace.json   plugin marketplace manifest (Claude Code + Copilot CLI)
  plugin.json        wb-plc plugin manifest

wb-plc/skills/       LLM-facing skill guides — one directory per skill, with
                     SKILL.md and optional references/, scripts/

wb_cli/              Python package — argparse root, plugins, lib/, commands/
  cli.py             argparse root, lazy-imports the plugin module
  context.py         CliContext with lazy handles (mqtt, rpc, systemd, ...)
  plugin.py          BasePlugin
  errors.py          error codes and exit codes
  output.py          JSON envelope rendering
  _registry.py       generated plugin list (make registry)
  lib/               subsystem handles
  commands/          one plugin per command group

tests/               pytest with FakeContext + a captured wb7 snapshot
debian/              .deb packaging (Architecture: all)
install-skills.sh    install skills into ~/.claude/skills, ~/.config/opencode/agents, etc.
.github/workflows/   CI (lint + tests on py3.9/3.11, .deb build) and release on tag v*
```

Background-job state lives at `/mnt/data/ai/wb-cli/jobs/<unit>.{sh,log,label,started}` — `wb-cli job` wraps `systemd-run --collect` and writes logs there.

## Development

Requires Python 3.9 (controller target). The [wirenboard/codestyle](https://github.com/wirenboard/codestyle) repo is included as a git submodule.

```bash
git clone --recurse-submodules git@github.com:wirenboard/wb-ai-skills.git
python3 -m venv .venv && .venv/bin/pip install -e . -r requirements-dev.txt

make test      # pytest
make lint      # black --check + isort --check + pylint (must be 10.00)
make fmt       # auto-format
make registry  # regenerate wb_cli/_registry.py after adding/removing a plugin
```

Conventions:

- Python 3.9 target — no `tomllib`, no PEP 695, no `match`.
- Double quotes, line length 110.
- Files ≤ 250 lines (`max-module-lines` in pylint).
- MQTT subscribe: `mosquitto_sub -F '%t\t%p'` (TAB separator, never `-v`); parse with `line.partition("\t")`.
- RPC: subprocess `mqtt-rpc-client -d <driver> -s <service> -m <method> -a <json>` (direct `python3-mqttrpc` is a future optimisation).

Adding a new command? Drop `wb_cli/commands/<name>.py` with `PLUGIN = MyPlugin()`, run `make registry`, write a test.

## Versioning

The repo ships **two artifacts with two independent versions**, because they evolve on different cadences:

- **`wb-cli` package version** — what gets installed on the controller (`.deb`). Bumped on CLI-level changes: new commands, JSON contract changes, error codes.
- **`wb-plc` plugin version** — what AI agents pull from the marketplace. Bumped on skill-content changes: new skills, content edits, description improvements. **Iterates faster than the package** — a typo fix in a SKILL.md is a plugin bump, not a `.deb` rebuild.

Both follow [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`) but with version-stream-specific rules.

### `wb-cli` package version

Authoritative source: `debian/changelog`. Mirrored into `pyproject.toml` and `wb_cli/__init__.py` (a test in `tests/test_version.py` enforces the three agree).

- **PATCH** — bug fix, internal refactor, no contract change.
- **MINOR** — new command, new subcommand, new option, new field in a JSON envelope, new error code.
- **MAJOR** — backwards-incompatible: removed/renamed command, changed JSON shape, changed/removed error code, changed exit code.

Skip the bump for: CI tweaks, test-only changes, README wording, fixture updates.

### `wb-plc` plugin version

Single source: `.claude-plugin/plugin.json` (`"version": "X.Y.Z"`). No mirror, no lockstep.

- **PATCH** — typo, clarification, small description tweak inside an existing skill.
- **MINOR** — new skill added, new section inside an existing skill, new triggering keywords in description.
- **MAJOR** — backwards-incompatible: skill removed or renamed (would break references in user prompts and docs).

Users get the latest version automatically via `/plugin marketplace update wb-ai-skills` — no tag/release ceremony is required for plugin bumps.

### Cutting a `wb-cli` release

```bash
# 1. bump three files in lockstep, write a changelog entry
dch -i                                          # or edit debian/changelog
sed -i 's/version = "[^"]\+"/version = "X.Y.Z"/' pyproject.toml
sed -i 's/__version__ = "[^"]\+"/__version__ = "X.Y.Z"/' wb_cli/__init__.py

# 2. commit + tag + push
git commit -am "release X.Y.Z"
git tag -a vX.Y.Z -m "wb-cli vX.Y.Z"
git push && git push origin vX.Y.Z
```

`release.yml` checks that the tag matches `debian/changelog`, builds the `.deb`, and publishes a GitHub Release with the package attached.

### Bumping the plugin

Just edit `.claude-plugin/plugin.json`:

```bash
sed -i 's/"version": "[^"]\+"/"version": "X.Y.Z"/' .claude-plugin/plugin.json
git commit -am "wb-plc X.Y.Z: <what changed>"
git push
```

No tag — the marketplace reads `main` by default, users `/plugin marketplace update` to pick it up.

## Contributing

- Open a PR against `main`. CI (`make lint` + `make test` on Python 3.9 / 3.11, plus `.deb` build) must be green.
- Keep modules under 250 lines (`max-module-lines` in pylint).
- **Every new command or behaviour change requires tests.** Cover the success path and every new error code. No exceptions.
- **Every new command must be manually verified on a real controller** before merging. `ssh root@<controller> wb-cli <command>` — confirm it works end-to-end.
- Tests live next to the code they exercise; aim for one test per success path and one per error code.
- Adding a plugin: create `wb_cli/commands/<name>.py` with `PLUGIN = MyPlugin()`, run `make registry`, add tests, verify on hardware, bump the version.
- Don't introduce a new error code unless the caller actually needs to branch on it — reuse what's there.

## License

MIT
