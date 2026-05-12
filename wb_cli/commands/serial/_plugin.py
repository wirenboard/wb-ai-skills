"""Serial plugin — registers all subcommands and dispatches."""

from __future__ import annotations

import argparse

from wb_cli.commands.serial import _actions
from wb_cli.commands.serial._actions import _fmt_hex
from wb_cli.plugin import BasePlugin


class SerialPlugin(BasePlugin):
    name = "serial"
    help = "serial port ops: send, wb-scan, device-params, device-set, add-devices, templates, devices, ports"
    # `serial wb-scan` draws its own ProgressBar; don't double up.
    auto_spinner = False

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Serial / RS-485 device operations.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")
        _actions.register_all(sub)

    def dispatch(self, ctx) -> dict:
        return _actions.dispatch(ctx)

    def render(self, result):  # pylint: disable=too-many-return-statements
        if "request" in result:
            return _render_send(result)
        if "parameters" in result:
            return _render_device_params(result)
        if "set" in result:
            return _render_device_set(result)
        if "devices" in result:
            return _render_devices(result)
        if "templates" in result and isinstance(result["templates"], list):
            names = result["templates"]
            return "\n".join([f"{len(names)} template(s):", *names])
        if "added" in result and "port" in result:
            return _add_devices_summary(result)
        return None


def _render_send(result):
    req = _fmt_hex(bytes.fromhex(result["request"]))
    lines = [f"→ {req}"]
    resp_hex = result.get("response", "")
    lines.append(f"← {_fmt_hex(bytes.fromhex(resp_hex))}" if resp_hex else "(no response)")
    return "\n".join(lines)


def _render_device_params(result):
    lines = [f"{result.get('device_type', '?')}  slave_id={result.get('slave_id', '?')}"]
    model = result.get("model", "")
    fw = result.get("fw", {})
    fw_ver = fw.get("version", "") if isinstance(fw, dict) else ""
    if model or fw_ver:
        lines.append("  " + "  ".join(filter(None, [f"model={model}", f"fw={fw_ver}"])))
    params = result.get("parameters") or {}
    if params:
        lines.append("parameters:")
        width = max(len(k) for k in params)
        for k, v in sorted(params.items()):
            lines.append(f"  {k.ljust(width)}  {v}")
    else:
        lines.append("(no configurable parameters)")
    return "\n".join(lines)


def _render_device_set(result):
    lines = [f"Updated {result.get('device_type', '?')} slave_id={result.get('slave_id', '?')}:"]
    for k, v in result["set"].items():
        lines.append(f"  {k} = {v}")
    return "\n".join(lines)


def _render_devices(result):
    if result["devices"] and "cfg" in result["devices"][0]:
        rows = [_scan_dev_row(dev) for dev in result["devices"]]
        return _scan_table(
            rows,
            scan_type=result.get("scan_type"),
            completed=result.get("completed", True),
            progress=result.get("progress"),
            hint=result.get("hint"),
            add_hint=result.get("add_hint"),
        )
    if not result["devices"]:
        scan_type = result.get("scan_type", "")
        kind = f" {scan_type}" if scan_type and scan_type != "full" else ""
        if not result.get("completed", True):
            return (
                f"no devices yet — {scan_type} scan timed out at "
                f"{result.get('progress', 0)}%. " + (result.get("hint") or "")
            ).rstrip()
        return f"no devices found by{kind} scan"
    if result["devices"] and "port_path" in result["devices"][0]:
        return _devices_table(result["devices"])
    return None


def _scan_dev_row(dev):
    cfg = dev.get("cfg", {})
    fw = dev.get("fw", {})
    return {
        "slave_id": str(cfg.get("slave_id", "?")),
        "signature": dev.get("device_signature", "?"),
        "sn": str(dev.get("sn", "?")),
        "port": dev.get("port", {}).get("path", "?"),
        "baud": str(cfg.get("baud_rate", "?")),
        "uart": f"{cfg.get('data_bits', '?')}{cfg.get('parity', '?')}{cfg.get('stop_bits', '?')}",
        "fw": fw.get("version", "?"),
    }


def _devices_table(rows):
    table = []
    for dev in rows:
        port = dev.get("port", {})
        table.append(
            {
                "slave_id": str(dev.get("slave_id", "?")),
                "device_type": dev.get("device_type") or "?",
                "protocol": dev.get("protocol") or "modbus",
                "port": dev.get("port_path") or "?",
                "baud": str(port.get("baud_rate", "?")),
                "uart": (
                    f"{port.get('data_bits', '?')}{port.get('parity', '?')}" f"{port.get('stop_bits', '?')}"
                ),
            }
        )
    columns = ["slave_id", "device_type", "protocol", "port", "baud", "uart"]
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
            line = f"  slave_id={dev['slave_id']}  {dev['device_type']}"
            if "slave_id_changed" in dev:
                line += f"  (address: {dev['slave_id_changed']})"
            if "baud_changed" in dev:
                line += f"  (baud: {dev['baud_changed']})"
            lines.append(line)
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
        cmds = add_hint.split("  ")
        if len(cmds) == 1:
            out.append(f"\nTo add to config: {add_hint}")
        else:
            out.append("\nTo add to config:")
            out.extend(f"  {cmd}" for cmd in cmds)
    return "\n".join(out)


PLUGIN = SerialPlugin()
