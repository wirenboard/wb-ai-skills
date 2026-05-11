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

    def render(self, result):
        # `modbus scan`: compact one-line-per-device.
        if "devices" in result and result["devices"] and "cfg" in result["devices"][0]:
            lines = [f"found {result.get('count', len(result['devices']))} device(s):"]
            for dev in result["devices"]:
                cfg = dev.get("cfg", {})
                fw = dev.get("fw", {})
                port = dev.get("port", {}).get("path", "?")
                lines.append(
                    f"  slave_id={cfg.get('slave_id', '?'):<4} "
                    f"{dev.get('device_signature', '?'):<10} "
                    f"sn={dev.get('sn', '?'):<12} "
                    f"port={port} "
                    f"fw={fw.get('version', '?')}"
                )
            return "\n".join(lines)
        # `modbus probe`: yes/no plus details.
        if "found" in result:
            if not result["found"]:
                return f"not found at slave_id={result.get('address')} on {result.get('port')}"
            sub = result.get("result") or {}
            return f"found  {sub.get('device_signature', '?')} " f"sn={sub.get('sn', '?')}"
        return None


PLUGIN = ModbusPlugin()
