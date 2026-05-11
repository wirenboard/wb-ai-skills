# wb-cli

[![CI](https://github.com/wirenboard/wb-ai-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/wirenboard/wb-ai-skills/actions/workflows/ci.yml)

Command-line interface to a [Wiren Board](https://wirenboard.com) controller.

Runs **on the controller**. Designed for two audiences:

1. **LLM agents** — SSH to the controller, call `wb-cli <command>`, get structured JSON back.
2. **Humans** — same commands, `--human` flag for readable output.

```bash
ssh root@wirenboard-A25NDEMJ wb-cli info
# → {"data": {"serial_number": "A25NDEMJ", "release_name": "wb-2602", ...}}

ssh root@wirenboard-A25NDEMJ wb-cli devices set wb-mr6c_52 K1 1
# → {"data": {"device": "wb-mr6c_52", "control": "K1", "value": "1", "ok": true}}
```

## Commands

| Command | What it does |
|---|---|
| `info` | Controller identity: serial, firmware, board revision, uptime |
| `devices list` | All devices with names and drivers |
| `devices controls <dev>` | Controls with values, types, readonly, error flags |
| `devices set <dev> <ctrl> <val>` | Set a control value (turn on/off, write) |
| `devices inventory` | Full device tree with metadata |
| `mqtt read <topic>` | Read retained MQTT value |
| `mqtt write <topic> <val>` | Publish MQTT message |
| `mqtt list [topic]` | List retained topics |
| `confed load <path>` | Load config via wb-mqtt-confed |
| `confed save <path> <json>` | Save config via wb-mqtt-confed |
| `rules list\|load\|save\|disable\|delete` | Manage wb-rules automation scripts |
| `history get <dev/ctrl>` | Time-series data from wb-mqtt-db |
| `history chart <dev/ctrl>` | Mermaid chart of historical data |
| `modbus scan\|probe\|templates\|ports\|add-devices` | RS-485 / Modbus operations |
| `cloud` | Cloud agent status |
| `serial-debug --port <path>` | RS-485 debug capture with auto-restore |
| `audit` | Quick health check |
| `snapshot save\|diff` | System state snapshots |
| `job run\|status\|tail\|cancel\|wait\|list` | Managed background tasks |
| `plugins` | List installed plugins |

Every command outputs a `{"data": {...}}` or `{"error": {...}}` JSON envelope on stdout. Exit codes: 0 (success), 1 (domain error), 2 (usage), 3 (environment).

## Install on a controller

Once published to the Wiren Board apt repository:

```bash
apt-get update && apt-get install -y wb-cli
```

Otherwise install the latest `.deb` from [GitHub Releases](https://github.com/wirenboard/wb-ai-skills/releases/latest):

```bash
URL=$(curl -fsSL https://api.github.com/repos/wirenboard/wb-ai-skills/releases/latest \
      | grep -oE 'https://[^"]+wb-cli_[^"]+\.deb' | head -1)
curl -fsSL -o /tmp/wb-cli.deb "$URL"
apt-get install -y /tmp/wb-cli.deb     # resolves python3-mqttrpc / python3-wb-common from wirenboard repo
```

## Development

Requires Python 3.9+ and [wirenboard/codestyle](https://github.com/wirenboard/codestyle) as a sibling clone.

```bash
git clone https://github.com/wirenboard/codestyle ../codestyle
python3 -m venv .venv && .venv/bin/pip install -e . -r requirements-dev.txt

make test      # run pytest
make lint      # black + isort + pylint
make fmt       # auto-format
make registry  # regenerate plugin registry
```

## Architecture

```
wb_cli/
  cli.py              entry point, argparse, dispatch
  context.py           CliContext with handles (mqtt, rpc, systemd, ...)
  plugin.py            CommandPlugin protocol, BasePlugin
  errors.py            error codes and exit codes
  output.py            JSON envelope rendering
  _registry.py         generated plugin list (make registry)
  lib/                 subsystem handles (controller, mqtt, rpc, shell, ...)
  commands/            one plugin per command group
    modbus/            subpackage for >4 subcommands
tests/
  conftest.py          controller_root fixture from captured data
  test_*.py            52 tests via FakeContext
skills/                10 LLM-facing methodology SKILL.md files
debian/                .deb packaging for wb7/bullseye
.github/workflows/     CI (lint + tests on py3.9/3.11, .deb build) + release on tag v*
```

See [DECISIONS.md](DECISIONS.md) for architectural rationale.

## License

MIT
