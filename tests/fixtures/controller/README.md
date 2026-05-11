# Controller fixtures — captured from a live wb7

Snapshot of a running controller's state, taken to enable offline development
of wb-cli without requiring a live device.

## Source

- **Controller:** A25NDEMJ (wb7, wb-2602/stable)
- **Captured:** 2026-05-10
- **OS:** Debian 11 bullseye
- **Kernel:** 6.8.0-wb140
- **wb-fw-version:** 202505010753

## Layout

```
identity/        — controller identity files (release, fw, sn, device-tree)
system/          — /proc/loadavg, /proc/meminfo, df, uptime
systemd/         — `systemctl --failed`, list-units, per-unit status/show/cat for key services
journal/         — `journalctl --output=json` samples (recent, per-unit, errors)
network/         — `ip -j addr/route/link`, `nmcli` outputs
configs/         — /etc/wb-mqtt-*.conf, apt-sources, sample wb-rules rule
mqtt/            — retained-topic dumps (TAB-separated: `topic\tpayload`)
                   • all-retained.tsv
                   • devices-meta.tsv
                   • controls-meta.tsv
                   • controls-values.tsv
modbus/          — wb-mqtt-serial template samples + listing of all 250+
rpc/             — sample MQTT-RPC responses (raw JSON-RPC envelopes)
                   • confed/Editor/Load
                   • wbrules/Editor/{List,Load}
                   • db_logger/history/{get_channels,get_values}
                   • wb-mqtt-serial/{config,ports}/Load
packages/        — dpkg -l (full), apt-mark showmanual, wb-* filtered
python-libs/     — REFERENCE: source of python3-mqttrpc + python3-wb-common
                   + the /usr/bin/mqtt-rpc-client wrapper script.
                   Use these to understand the API; do NOT vendor them
                   into wb_cli/.
```

## How fixtures were captured

Single SSH session running a bash heredoc (`mosquitto_sub -F '%t\t%p'`,
`systemctl --output=json`, `cp /etc/...`, etc.), tarred up and downloaded.
See git log for the exact capture command.

For RPC fixtures the WB-bundled binary `mqtt-rpc-client` was used:

```bash
mqtt-rpc-client -d confed -s Editor -m Load -a '{"path":"/etc/wb-mqtt-serial.conf"}'
```

This binary is itself a thin Python wrapper around
`mqttrpc.client.TMQTTRPCClient` (see `python-libs/mqtt-rpc-client.py`).

## How to use these in tests

- `tests/lib/test_inventory.py` — feed `mqtt/devices-meta.tsv` +
  `mqtt/controls-meta.tsv` into the parser, assert structured output.
- `tests/lib/test_audit.py` — parse `packages/dpkg-l.txt`, expect known counts.
- `tests/lib/test_journal.py` — parse `journal/recent-100.json`, validate
  field extraction.
- `tests/lib/test_modbus_templates.py` — load templates, assert parameters
  defaults are extracted (e.g. WB-MAI6 `in1_type..in6_type`).
- `tests/lib/test_rpc.py` — mock the RPC layer, return contents of
  `rpc/confed-load-serial.json` etc., assert plugin behaviour.

The fixtures are **stable** — checked in, will not change without a
deliberate refresh. Tests should be reproducible offline.

## What's NOT here (intentionally)

- Live MQTT subscribe streams (no way to capture without keeping connection)
- wb-device-manager bus-scan flow (multi-step async; capture when implementing
  modbus scan plugin against a live controller)
- factoryreset, apt-upgrade outputs (destructive; capture in a sandbox VM if
  needed)

## Refreshing

To re-capture against a different controller (e.g. wb8 / wb-2507):

```bash
# adapt the heredoc in the original capture commit (search git log for
# "wb-cli: capture controller fixtures") and run against the new host.
```

Keep the directory structure stable; add a sibling `controller-wb8/` if
multiple snapshots are needed.
