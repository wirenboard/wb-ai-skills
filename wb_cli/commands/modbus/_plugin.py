"""Modbus plugin — registers all subcommands and dispatches."""

from __future__ import annotations

import argparse

from wb_cli.commands.modbus import _actions
from wb_cli.plugin import BasePlugin


class ModbusPlugin(BasePlugin):
    name = "modbus"
    help = "RS-485 / Modbus: scan, probe, templates, device-info, ports, add-devices"

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


PLUGIN = ModbusPlugin()
