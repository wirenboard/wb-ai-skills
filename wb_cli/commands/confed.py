"""``wb-cli confed`` — load / save service configs via wb-mqtt-confed RPC."""

from __future__ import annotations

import argparse
import json

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class ConfedPlugin(BasePlugin):
    name = "confed"
    help = "read and write service config files through wb-mqtt-confed"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "wb-mqtt-confed knows which JSON config goes with which service and\n"
                "reloads the service after a save. Prefer it over editing files in\n"
                "/etc/ directly. The schema for each config is under\n"
                "/usr/share/wb-mqtt-confed/schemas/."
            ),
            epilog=(
                "Examples:\n"
                "  wb-cli confed load /etc/wb-mqtt-serial.conf\n"
                '  wb-cli confed save /etc/wb-scenarios.conf "$(jq -c . my-scenarios.json)"\n'
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser(
            "load",
            help="read a config managed by wb-mqtt-confed",
            description="Return the JSON content of the config at <path>.",
        )
        p.add_argument("path", help="absolute path of a config (e.g. /etc/wb-mqtt-serial.conf)")

        p = sub.add_parser(
            "save",
            help="overwrite a config and reload the owning service",
            description="Replace the config at <path> with <content>; <content> must be valid JSON.",
        )
        p.add_argument("path", help="absolute path of a config")
        p.add_argument("content", help="full JSON document (string)")

    def dispatch(self, ctx) -> dict:
        if ctx.args.subcmd == "load":
            return self._load(ctx)
        if ctx.args.subcmd == "save":
            return self._save(ctx)
        return {}

    def _load(self, ctx) -> dict:
        result = ctx.rpc.call("confed/Editor/Load", {"path": ctx.args.path})
        if isinstance(result, dict) and "content" in result:
            return {"path": ctx.args.path, "config": result["content"]}
        return {"path": ctx.args.path, "config": result}

    def _save(self, ctx) -> dict:
        try:
            content = json.loads(ctx.args.content)
        except json.JSONDecodeError as exc:
            raise WbCliError(
                code="CONFED_INVALID_JSON",
                message=f"Content is not valid JSON: {exc}",
                details={"content": ctx.args.content},
                exit_code=ExitCode.USAGE,
            ) from exc

        ctx.rpc.call(
            "confed/Editor/Save",
            {"path": ctx.args.path, "content": content},
        )
        return {"path": ctx.args.path, "ok": True}


PLUGIN = ConfedPlugin()
