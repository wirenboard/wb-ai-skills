"""Modbus plugin — registers all subcommands and dispatches."""

from __future__ import annotations

import argparse

from wb_cli.commands.modbus import _actions
from wb_cli.plugin import BasePlugin


class ModbusPlugin(BasePlugin):
    name = "modbus"
    help = "RS-485 / Modbus: scan, probe, templates, device-info, ports, add-devices"
    # `modbus scan` draws its own ProgressBar; don't double up.
    auto_spinner = False

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Modbus / RS-485 device operations.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")
        _actions.register_all(sub)

    def dispatch(self, ctx) -> dict:
        return _actions.dispatch(ctx)

    def render(self, result):  # pylint: disable=too-many-return-statements
        # `modbus scan`: header + table.
        if "devices" in result and result["devices"] and "cfg" in result["devices"][0]:
            rows = []
            for dev in result["devices"]:
                cfg = dev.get("cfg", {})
                fw = dev.get("fw", {})
                rows.append(
                    {
                        "slave_id": str(cfg.get("slave_id", "?")),
                        "signature": dev.get("device_signature", "?"),
                        "sn": str(dev.get("sn", "?")),
                        "port": dev.get("port", {}).get("path", "?"),
                        "baud": str(cfg.get("baud_rate", "?")),
                        "uart": (
                            f"{cfg.get('data_bits', '?')}{cfg.get('parity', '?')}"
                            f"{cfg.get('stop_bits', '?')}"
                        ),
                        "fw": fw.get("version", "?"),
                    }
                )
            return _scan_table(
                rows,
                scan_type=result.get("scan_type"),
                completed=result.get("completed", True),
                progress=result.get("progress"),
                hint=result.get("hint"),
                add_hint=result.get("add_hint"),
            )
        if "devices" in result and not result["devices"]:
            scan_type = result.get("scan_type", "")
            kind = f" {scan_type}" if scan_type and scan_type != "full" else ""
            if not result.get("completed", True):
                return (
                    f"no devices yet — {scan_type} scan timed out at "
                    f"{result.get('progress', 0)}%. " + (result.get("hint") or "")
                ).rstrip()
            return f"no devices found by{kind} scan"
        # `modbus devices`: configured-device table from /etc/wb-mqtt-serial.conf.
        if "devices" in result and result["devices"] and "port_path" in result["devices"][0]:
            return _devices_table(result["devices"])
        # `modbus templates`: long flat list, one per line.
        if "templates" in result and isinstance(result["templates"], list):
            names = result["templates"]
            return "\n".join([f"{len(names)} template(s):", *names])
        # `modbus probe`: yes/no plus details.
        if "found" in result:
            if not result["found"]:
                return f"not found at slave_id={result.get('address')} on {result.get('port')}"
            sub = result.get("result") or {}
            return f"found  {sub.get('device_signature', '?')} sn={sub.get('sn', '?')}"
        # `modbus add-devices`: summary of what was added / skipped.
        if "added" in result and "port" in result:
            return _add_devices_summary(result)
        return None


def _devices_table(rows):
    table = []
    for dev in rows:
        port = dev.get("port", {})
        table.append(
            {
                "slave_id": str(dev.get("slave_id", "?")),
                "device_type": dev.get("device_type") or "?",
                "port": dev.get("port_path") or "?",
                "baud": str(port.get("baud_rate", "?")),
                "uart": (
                    f"{port.get('data_bits', '?')}{port.get('parity', '?')}" f"{port.get('stop_bits', '?')}"
                ),
            }
        )
    columns = ["slave_id", "device_type", "port", "baud", "uart"]
    widths = {c: max(len(c), *(len(r[c]) for r in table)) for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    body = ["  ".join(r[c].ljust(widths[c]) for c in columns) for r in table]
    return "\n".join([f"{len(rows)} device(s) in /etc/wb-mqtt-serial.conf:", header, sep, *body])


def _add_devices_summary(result):
    port = result.get("port", "?")
    added = result.get("added", [])
    skipped = result.get("skipped", [])
    warnings = result.get("warnings", [])
    lines = []
    if added:
        lines.append(f"Added {len(added)} device(s) to {port}:")
        for dev in added:
            lines.append(f"  slave_id={dev['slave_id']}  {dev['device_type']}")
    else:
        lines.append(f"No new devices added to {port}")
    if skipped:
        lines.append(
            f"Skipped {len(skipped)} already in config: slave_id={', '.join(str(s) for s in skipped)}"
        )
    for w in warnings:
        lines.append(f"WARNING: {w}")
    return "\n".join(lines)


def _scan_table(  # pylint: disable=too-many-arguments
    rows, *, scan_type=None, completed=True, progress=None, hint=None, add_hint=None
):
    columns = ["slave_id", "signature", "sn", "port", "baud", "uart", "fw"]
    widths = {col: max(len(col), *(len(r[col]) for r in rows)) for col in columns}
    header = "  ".join(col.ljust(widths[col]) for col in columns)
    sep = "  ".join("-" * widths[col] for col in columns)
    body = ["  ".join(r[col].ljust(widths[col]) for col in columns) for r in rows]
    title = f"{scan_type} scan — {len(rows)} device(s):" if scan_type else f"{len(rows)} device(s):"
    if not completed:
        title = (
            f"{scan_type or ''} scan — TIMEOUT at {progress}%, " f"{len(rows)} device(s) seen so far:"
        ).strip()
    out = [title, header, sep, *body]
    if not completed and hint:
        out.append(f"hint: {hint}")
    if completed and add_hint:
        out.append(f"\nTo add to config: {add_hint}")
    return "\n".join(out)


PLUGIN = ModbusPlugin()
