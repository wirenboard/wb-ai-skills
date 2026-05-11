"""``wb-cli plugins`` — list installed plugins."""

from __future__ import annotations

import argparse
from typing import Optional

from wb_cli import __version__
from wb_cli._registry import BUILTIN_PLUGINS
from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class PluginsPlugin(BasePlugin):
    name = "plugins"
    help = "list every plugin this wb-cli build knows about"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "Self-introspection: which commands are compiled into this wb-cli.\n"
                "Pass a plugin name to get its short help and Python module path."
            ),
        )
        parser.add_argument(
            "name",
            nargs="?",
            metavar="<name>",
            help="show details for one plugin",
        )

    def dispatch(self, ctx) -> dict:
        target: Optional[str] = ctx.args.name

        if target is not None:
            entry = BUILTIN_PLUGINS.get(target)
            if entry is None:
                raise WbCliError(
                    code="PLUGIN_NOT_FOUND",
                    message=f"No plugin named '{target}'",
                    hint="Run: wb-cli plugins",
                    details={"name": target, "available": sorted(BUILTIN_PLUGINS)},
                    exit_code=ExitCode.DOMAIN,
                )
            module_path, help_text = entry
            return {"name": target, "help": help_text, "module": module_path}

        plugins = [
            {"name": name, "help": help_text, "module": mod}
            for name, (mod, help_text) in sorted(BUILTIN_PLUGINS.items())
        ]
        return {
            "wb_cli_version": __version__,
            "plugins": plugins,
            "count": len(plugins),
        }


PLUGIN = PluginsPlugin()
