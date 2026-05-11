"""``wb-cli rules`` — automation rules (wb-rules JS files)."""

from __future__ import annotations

import argparse

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class RulesPlugin(BasePlugin):
    name = "rules"
    help = "automation rules / scenarios: list, load, save, disable, delete"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Manage wb-rules automation scripts.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        for action in ("list",):
            p = sub.add_parser(action, help="list all rules")
            p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("load", help="load rule source by name")
        p.add_argument("name", help="rule file name (without .js)")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("save", help="save rule source")
        p.add_argument("name", help="rule file name (without .js)")
        p.add_argument("content", help="JavaScript source code")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("disable", help="disable a rule")
        p.add_argument("name", help="rule file name")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("delete", help="delete a rule")
        p.add_argument("name", help="rule file name")
        p.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:  # pylint: disable=too-many-return-statements
        subcmd = ctx.args.subcmd
        if subcmd == "list":
            return self._list(ctx)
        if subcmd == "load":
            return self._load(ctx)
        if subcmd == "save":
            return self._save(ctx)
        if subcmd == "disable":
            return self._disable(ctx)
        if subcmd == "delete":
            return self._delete(ctx)
        return {}

    def _list(self, ctx) -> dict:
        result = ctx.rpc.call("wbrules/Editor/List", {})
        items = result if isinstance(result, list) else result.get("files", [])
        rules = []
        for item in items:
            if isinstance(item, dict):
                path = item.get("virtualPath", "")
                name = path[:-3] if path.endswith(".js") else path
                rules.append(
                    {
                        "name": name,
                        "path": path,
                        "enabled": item.get("enabled", True),
                    }
                )
            else:
                rules.append({"name": str(item)})
        return {"rules": rules, "count": len(rules)}

    def _load(self, ctx) -> dict:
        _validate_name(ctx.args.name)
        result = ctx.rpc.call(
            "wbrules/Editor/Load",
            {"path": ctx.args.name + ".js"},
        )
        return {"name": ctx.args.name, "content": result}

    def _save(self, ctx) -> dict:
        _validate_name(ctx.args.name)
        ctx.rpc.call(
            "wbrules/Editor/Save",
            {"path": ctx.args.name + ".js", "content": ctx.args.content},
        )
        return {"name": ctx.args.name, "ok": True}

    def _disable(self, ctx) -> dict:
        _validate_name(ctx.args.name)
        ctx.rpc.call(
            "wbrules/Editor/Save",
            {"path": ctx.args.name + ".js.disabled", "content": ""},
        )
        return {"name": ctx.args.name, "ok": True}

    def _delete(self, ctx) -> dict:
        _validate_name(ctx.args.name)
        ctx.rpc.call(
            "wbrules/Editor/Remove",
            {"path": ctx.args.name + ".js"},
        )
        return {"name": ctx.args.name, "ok": True}


def _validate_name(name: str) -> None:
    if "/" in name:
        raise WbCliError(
            code="RULES_NAME_INVALID",
            message=f"Rule name must not contain '/': '{name}'",
            details={"name": name},
            exit_code=ExitCode.DOMAIN,
        )
    if name.endswith(".js"):
        raise WbCliError(
            code="RULES_NAME_INVALID",
            message=f"Pass rule name without .js suffix: '{name}'",
            hint=f"Use: wb-cli rules load {name[:-3]}",
            details={"name": name},
            exit_code=ExitCode.DOMAIN,
        )


PLUGIN = RulesPlugin()
