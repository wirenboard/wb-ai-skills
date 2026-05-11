# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`wb-cli` — CLI utility for Wiren Board controllers. Runs on the controller, called by LLM agents via SSH. See [`README.md`](README.md) for usage, [`DECISIONS.md`](DECISIONS.md) for architecture.

## Code layout

- `wb_cli/` — package source. Files ≤250 lines (`max-module-lines` in pylint).
- `wb_cli/commands/` — one plugin per command. `modbus/` is a subpackage (>4 subcmds).
- `wb_cli/lib/` — subsystem handles (controller, mqtt, rpc, shell, systemd, journal, job).
- `tests/` — pytest, FakeContext, fixtures from a live wb7 in `tests/fixtures/controller/`.
- `debian/` — .deb packaging for Debian 11 bullseye / wb7.

## Build and check

```bash
make fmt       # black + isort
make lint      # black --check + isort --check + pylint (must be 10.00)
make test      # pytest
make registry  # regenerate wb_cli/_registry.py after adding/removing plugins
```

Requires [wirenboard/codestyle](https://github.com/wirenboard/codestyle) cloned as `../codestyle`.

## Conventions

- Python 3.9 target (Debian 11 bullseye). No `tomllib`, no PEP 695.
- Double quotes, line length 110, PEP 8 with wirenboard/codestyle overrides.
- JSON output: `{"data": {...}}` or `{"error": {...}}` envelope. `snake_case` keys.
- Error codes: `SCREAMING_SNAKE_CASE`, never renamed after release.
- Serial number `A25NDEMJ` in examples (8 chars).
- MQTT: `mosquitto_sub -F '%t\t%p'` (TAB separator, never `-v`).
