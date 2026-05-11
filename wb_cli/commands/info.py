"""``wb-cli info`` — controller identity and basic system facts.

Returns serial number, firmware release, board revision, hostname,
uptime, and device-tree metadata in a single JSON envelope.
"""

from __future__ import annotations

import argparse

from wb_cli.plugin import BasePlugin


class InfoPlugin(BasePlugin):
    name = "info"
    help = "controller identity: serial number, firmware, board revision, uptime"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Show controller identity and basic system facts.",
        )
        parser.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:
        return ctx.controller.to_dict()

    def render(self, result):
        fields = ["serial_number", "release_name", "fw_version", "hostname", "uptime_seconds"]
        rows = [(f, result.get(f, "")) for f in fields if f in result]
        if not rows:
            return None
        width = max(len(k) for k, _ in rows)
        return "\n".join(f"{k.ljust(width)}  {v}" for k, v in rows)


PLUGIN = InfoPlugin()
