# wb-cli

[![CI](https://github.com/wirenboard/wb-ai-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/wirenboard/wb-ai-skills/actions/workflows/ci.yml)

Command-line interface to a [Wiren Board](https://wirenboard.com) controller, plus a set of methodology skills for LLM agents that drive it over SSH.

Runs **on the controller**. Built for LLM agents and operators: SSH in, call `wb-cli <command>`, get a structured JSON envelope back. Long-running commands draw a progress bar on stderr when the terminal is a TTY; JSON on stdout stays clean either way.

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

## Commands

| Plugin | What it covers |
|---|---|
| `info` | Controller identity: serial number, firmware release, board revision, hostname, uptime |
| `audit` | Quick health check (failed units + identity) |
| `cloud` | Wiren Board cloud-agent status |
| `dev` | Devices and controls — list, read, write through the wb-rules `<device>/<control>` form |
| `mqtt` | Raw MQTT: read retained, write, list, live subscribe |
| `mqtt-debug` | Verbose mosquitto PUBLISH tracing — structured `{client_id, topic, qos, retain, …}` records, optional inline / background capture |
| `confed` | Read and write service config files through wb-mqtt-confed (handles validation + service reload) |
| `rules` | Manage wb-rules automation scripts |
| `history` | Time-series data from wb-mqtt-db (raw rows) |
| `serial` | RS-485 / Modbus operations through wb-mqtt-serial and wb-device-manager (incl. `wb-fw` firmware update — folded in as a subcommand in 1.8.0) |
| `serial-debug` | RS-485 driver debug capture (toggles wb-mqtt-serial's `Debug` control with auto-restore) |
| `snapshot` | Capture and diff small JSON snapshots of controller state |
| `job` | Long-running commands as transient systemd units |
| `plugins` | Self-introspection: which commands this wb-cli build knows about |

Each plugin has its own `--help` with full subcommand list, flags and worked examples — that's the authoritative reference and always matches the installed version:

```bash
wb-cli --help                  # top-level — all plugins
wb-cli <plugin> --help         # subcommands of one plugin
wb-cli <plugin> <action> --help  # flags for one action
```

## Output modes

`wb-cli` emits **human-friendly** output (tables / key-value lines) by default everywhere — including pipes and SSH without a TTY. JSON is opt-in via `--json` or `WB_CLI_OUTPUT=json`. A stderr spinner / progress bar is drawn for long-running calls only when stderr is a TTY, so JSON to stdout always stays clean.

The default flipped to human in 1.0 because the previous "auto-detect based on `stdout.isatty()`" rule meant that piping wb-cli through `grep` got JSON — which is rarely what a human-on-SSH wants. LLM agents and scripts that need parsable output pass `--json` explicitly.

Override anywhere:

```bash
wb-cli --json dev               # force JSON (LLM agents / scripts)
WB_CLI_OUTPUT=json wb-cli info  # same via env (good for shells)
WB_CLI_NO_SPINNER=1 wb-cli ...  # silence the spinner regardless of mode
```

The JSON envelope is the stable, machine-readable contract:

- **Success:** `{"data": { ... }}` — `snake_case` keys, arrays are always arrays.
- **Error:** `{"error": {"code": "SCREAMING_SNAKE", "message": "...", "hint": "...", "details": { ... }}}`.

Exit codes: **0** success · **1** domain error · **2** usage · **3** environment · **130** SIGINT. Error codes are stable across releases.

## Install on a controller

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

## Skills for LLM agents

The `skills/` directory holds nine methodology guides for LLM agents working with Wiren Board over SSH:

| Skill | What it covers |
|---|---|
| `wiren-board` | Master entry: discovery, SSH conventions, wb-cli, install fallback. **Load first.** |
| `wb-troubleshooting` | Failed units, disk, kernel mismatch, Docker, general diagnostics. |
| `wb-serial` | RS-485/Modbus: custom templates, device config via confed, bus diagnostics (CRC, timeouts). |
| `wb-rules` | wb-rules JavaScript automation (ES5, virtual devices, cron). |
| `wb-mqtt-broker` | MQTT broker config: auth, ACL, TLS, bridges, `mqtt-debug` PUBLISH tracing. |
| `wb-network` | WiFi, 4G/GSM, VPN, failover, modem diagnostics, NTP. |
| `wb-zigbee` | Zigbee via zigbee2mqtt (pairing, OTA, native vs Docker). |
| `wb-controller-backup` | Full controller backup and restore. |
| `wb-dev` | Writing software / integrations for WB: custom daemons, protocol bridges, MQTT conventions, MQTT-RPC, codestyle, wbdev cross-compilation, Debian packaging. |

Install for your agent runtime:

**Linux / macOS** — use the install script:

```bash
./install-skills.sh claude              # → ./.claude/commands/
./install-skills.sh claude --global     # → ~/.claude/commands/
./install-skills.sh opencode            # → ./.opencode/agents/   (frontmatter rewritten)
./install-skills.sh opencode --global   # → ~/.config/opencode/agents/
./install-skills.sh manual --dest <dir> # → <dir>  (frontmatter stripped to name+description)

./install-skills.sh uninstall claude --global   # remove installed skills
```

**Windows** — copy the files from `skills/` manually to the agent's commands folder:

| Agent | Destination |
|---|---|
| Claude Code (user-wide) | `%USERPROFILE%\.claude\commands\` |
| Claude Code (project) | `.claude\commands\` inside the project |
| OpenCode (user-wide) | `%APPDATA%\opencode\agents\` |

For OpenCode, also replace `allowed-tools:` with `mode: primary` in each file's frontmatter.

The `.deb` also installs the skills into `/usr/share/wb-cli/skills/` on the controller, so an LLM agent can read them over SSH.

## Architecture

```
wb_cli/
  cli.py              argparse root, lazy-imports the plugin module
  context.py          CliContext with lazy handles (mqtt, rpc, systemd, ...)
  plugin.py           BasePlugin
  errors.py           error codes and exit codes
  output.py           JSON envelope rendering
  _registry.py        generated plugin list (make registry)
  lib/                subsystem handles (controller, mqtt, mqtt_log, rpc, shell, systemd,
                      journal, job, serial_conf, serial_port, modbus_crc, modbus_frame, templates)
  commands/           one plugin per command group; serial/ is a subpackage (_register, _scan,
                      _add, _actions, _plugin)
tests/                pytest with FakeContext + a captured wb7 snapshot in tests/fixtures/
skills/               LLM-facing skill guides, one .md per skill (see above)
debian/               .deb packaging (Architecture: all)
.github/workflows/    CI (lint + tests on py3.9/3.11, .deb build) and release on tag v*
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

`wb-cli` follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`):

- **PATCH** (`0.1.0 → 0.1.1`) — bug fix, internal refactor, doc-only or CI-only change that ships in the next release.
- **MINOR** (`0.1.0 → 0.2.0`) — new command, new subcommand, new option, new error code, new field in a JSON envelope. Existing callers keep working.
- **MAJOR** (`0.1.0 → 1.0.0`) — backwards-incompatible change: a removed or renamed command, a changed JSON shape, a changed/removed error code, a changed exit code.

### When to bump

Bump the version **in the same commit that introduces a user-visible change** — anything that affects the `.deb` contents or the JSON contract. Don't batch unrelated fixes under one bump; cut a fresh patch release per round of fixes.

You can skip the bump for changes that don't affect what installs on a controller:

- CI / GitHub Actions workflow tweaks
- Tests that don't change behaviour
- README / SKILL.md / commit-message wording
- `tests/fixtures/` snapshot updates

### How to bump

Three files have to agree (a test in `tests/test_version.py` enforces this):

```
debian/changelog       # authoritative; release.yml verifies tag matches
pyproject.toml         # `version = "X.Y.Z"`
wb_cli/__init__.py     # `__version__ = "X.Y.Z"`
```

Either run `dch -i` (Debian helper) and mirror the version into the two Python files, or edit all three by hand.

### Cutting a release

```bash
# 1. bump versions in lockstep, write a changelog entry
dch -i                                          # or edit debian/changelog
sed -i 's/version = "[^"]\+"/version = "X.Y.Z"/' pyproject.toml
sed -i 's/__version__ = "[^"]\+"/__version__ = "X.Y.Z"/' wb_cli/__init__.py

# 2. commit + tag + push
git commit -am "release X.Y.Z"
git tag -a vX.Y.Z -m "wb-cli vX.Y.Z"
git push && git push origin vX.Y.Z
```

`release.yml` checks that the tag matches `debian/changelog`, builds the `.deb`, and publishes a GitHub Release with the package attached.

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
