"""``wb-cli confed`` — load / save configs via wb-mqtt-confed RPC."""

from __future__ import annotations

import argparse
import json

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class ConfedPlugin(BasePlugin):
    name = "confed"
    help = "configuration editor: load and save service configs via confed"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Load or save configs through wb-mqtt-confed.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser("load", help="load a config by confed path")
        p.add_argument("path", help="confed config path")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("save", help="save a config by confed path")
        p.add_argument("path", help="confed config path")
        p.add_argument("content", help="JSON content to save")
        p.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:
        if ctx.args.subcmd == "load":
            return self._load(ctx)
        if ctx.args.subcmd == "save":
            return self._save(ctx)
        return {}

    def _load(self, ctx) -> dict:
        result = ctx.rpc.call(
            "confed/Editor/Load",
            {"path": ctx.args.path},
        )
        if isinstance(result, dict) and "content" in result:
            return {"path": ctx.args.path, "config": result["content"]}
        return {"path": ctx.args.path, "config": result}

    def _save(self, ctx) -> dict:
        # confed expects parsed JSON, not a string
        try:
            content = json.loads(ctx.args.content)
        except json.JSONDecodeError as exc:
            raise WbCliError(
                code="CONFED_INVALID_JSON",
                message=f"Content is not valid JSON: {exc}",
                details={"content": ctx.args.content},
                exit_code=ExitCode.DOMAIN,
            ) from exc

        ctx.rpc.call(
            "confed/Editor/Save",
            {"path": ctx.args.path, "content": content},
        )
        return {"path": ctx.args.path, "ok": True}


PLUGIN = ConfedPlugin()
