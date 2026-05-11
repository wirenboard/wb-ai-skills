"""``wb-cli rules`` — automation rules (wb-rules JS files)."""

from __future__ import annotations

import argparse

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class RulesPlugin(BasePlugin):
    name = "rules"
    help = "manage wb-rules automation scripts (list / read / save / disable / delete)"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "wb-rules .js files live in /etc/wb-rules/. This command edits them\n"
                "through the wb-rules RPC editor, which also reloads the daemon on save."
            ),
            epilog=(
                "Examples:\n"
                "  wb-cli rules list\n"
                "  wb-cli rules load myrule                # rule name without .js\n"
                '  wb-cli rules save myrule "$(cat my.js)"\n'
                "  wb-cli rules disable myrule             # renamed to myrule.js.disabled\n"
                "  wb-cli rules delete myrule\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        sub.add_parser(
            "list",
            help="list every rule on the controller",
            description="Names, paths and enabled flag for every .js under /etc/wb-rules/.",
        )

        p = sub.add_parser(
            "load",
            help="print the source of a rule",
            description="Fetch <name>.js from the editor; the result is the JavaScript source.",
        )
        p.add_argument("name", help="rule file name without .js, e.g. `lighting`")

        p = sub.add_parser(
            "save",
            help="create or overwrite a rule",
            description="Write JavaScript content as <name>.js. wb-rules reloads on save.",
        )
        p.add_argument("name", help="rule file name without .js")
        p.add_argument("content", help="JavaScript source")

        p = sub.add_parser(
            "disable",
            help="disable a rule (rename .js -> .js.disabled, no reload risk)",
            description=(
                "Rename <name>.js to <name>.js.disabled so wb-rules ignores it. Source is preserved."
            ),
        )
        p.add_argument("name", help="rule file name without .js")

        p = sub.add_parser(
            "enable",
            help="re-enable a previously disabled rule (rename .js.disabled -> .js)",
            description=("Inverse of `disable`: rename <name>.js.disabled back to <name>.js."),
        )
        p.add_argument("name", help="rule file name without .js")

        p = sub.add_parser(
            "delete",
            help="permanently remove a rule",
            description="Delete <name>.js. There's no trash; use `disable` if you might want it back.",
        )
        p.add_argument("name", help="rule file name without .js")

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
        if subcmd == "enable":
            return self._enable(ctx)
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
        try:
            result = ctx.rpc.call(
                "wbrules/Editor/Load",
                {"path": ctx.args.name + ".js"},
            )
        except WbCliError as exc:
            if exc.code == "RPC_ERROR_RESPONSE" and "not found" in exc.message.lower():
                raise WbCliError(
                    code="RULES_NOT_FOUND",
                    message=f"Rule '{ctx.args.name}' not found",
                    details={"name": ctx.args.name},
                    exit_code=ExitCode.DOMAIN,
                ) from exc
            raise
        # wb-rules' Editor/Load returns either a bare string (old) or
        # ``{"content": "<source>", "enabled": true}`` (current). Unwrap so
        # the user gets the source they asked for.
        content = result.get("content", result) if isinstance(result, dict) else result
        return {"name": ctx.args.name, "content": content}

    def _save(self, ctx) -> dict:
        _validate_name(ctx.args.name)
        ctx.rpc.call(
            "wbrules/Editor/Save",
            {"path": ctx.args.name + ".js", "content": ctx.args.content},
        )
        return {"name": ctx.args.name, "ok": True}

    def _disable(self, ctx) -> dict:
        _validate_name(ctx.args.name)
        return _rename_via_shell(
            ctx,
            f"/etc/wb-rules/{ctx.args.name}.js",
            f"/etc/wb-rules/{ctx.args.name}.js.disabled",
            kind="disable",
        )

    def _enable(self, ctx) -> dict:
        _validate_name(ctx.args.name)
        return _rename_via_shell(
            ctx,
            f"/etc/wb-rules/{ctx.args.name}.js.disabled",
            f"/etc/wb-rules/{ctx.args.name}.js",
            kind="enable",
        )

    def _delete(self, ctx) -> dict:
        _validate_name(ctx.args.name)
        ctx.rpc.call(
            "wbrules/Editor/Remove",
            {"path": ctx.args.name + ".js"},
        )
        return {"name": ctx.args.name, "ok": True}


def _rename_via_shell(ctx, src: str, dst: str, *, kind: str) -> dict:
    """Rename a rule file in place, bypassing the wb-rules editor.

    The Editor RPC rejects any save/rename whose target doesn't end in ``.js``,
    so disable/enable can't go through it. wb-rules watches /etc/wb-rules/ via
    inotify, so a plain ``mv`` is enough to make it reload.
    """
    rc, _, _ = ctx.shell.run(["test", "-f", src])
    if rc != 0:
        raise WbCliError(
            code="RULES_NOT_FOUND",
            message=f"{src} does not exist — cannot {kind}",
            details={"path": src},
            exit_code=ExitCode.DOMAIN,
        )
    rc, _, _ = ctx.shell.run(["test", "-e", dst])
    if rc == 0:
        raise WbCliError(
            code="RULES_TARGET_EXISTS",
            message=f"{dst} already exists — refusing to overwrite",
            hint=f"Remove or rename {dst} first.",
            details={"path": dst},
            exit_code=ExitCode.DOMAIN,
        )
    rc, _, stderr = ctx.shell.run(["mv", src, dst])
    if rc != 0:
        raise WbCliError(
            code="RULES_RENAME_FAILED",
            message=f"mv {src} -> {dst} failed: {stderr.strip() or 'unknown error'}",
            details={"src": src, "dst": dst, "stderr": stderr},
            exit_code=ExitCode.ENVIRONMENT,
        )
    return {"ok": True, "from": src, "to": dst}


def _validate_name(name: str) -> None:
    if "/" in name:
        raise WbCliError(
            code="RULES_NAME_INVALID",
            message=f"Rule name must not contain '/': '{name}'",
            details={"name": name},
            exit_code=ExitCode.USAGE,
        )
    if name.endswith(".js") or name.endswith(".js.disabled"):
        raise WbCliError(
            code="RULES_NAME_INVALID",
            message=f"Pass rule name without .js/.js.disabled suffix: '{name}'",
            hint=f"Use: wb-cli rules load {name.split('.')[0]}",
            details={"name": name},
            exit_code=ExitCode.USAGE,
        )


PLUGIN = RulesPlugin()
