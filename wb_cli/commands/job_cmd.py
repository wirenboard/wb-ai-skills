"""``wb-cli job`` — managed background tasks."""

from __future__ import annotations

import argparse

from wb_cli.plugin import BasePlugin


class JobPlugin(BasePlugin):
    name = "job"
    help = "background tasks: run, status, tail, cancel, wait, list"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Manage long-running background jobs.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser("run", help="start a background job")
        p.add_argument("label", help="short label for the job")
        p.add_argument("command", help="shell command to execute")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("status", help="show job status")
        p.add_argument("unit", help="job unit name")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("tail", help="show job log tail")
        p.add_argument("unit", help="job unit name")
        p.add_argument("-n", "--lines", type=int, default=50)
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("cancel", help="cancel a running job")
        p.add_argument("unit", help="job unit name")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("wait", help="wait for a job to complete")
        p.add_argument("unit", help="job unit name")
        p.add_argument(
            "--timeout",
            type=float,
            default=300.0,
            help="max wait time in seconds",
        )
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("list", help="list all known jobs")
        p.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:  # pylint: disable=too-many-return-statements
        subcmd = ctx.args.subcmd
        if subcmd == "run":
            return ctx.job.run(ctx.args.label, ctx.args.command)
        if subcmd == "status":
            return ctx.job.status(ctx.args.unit)
        if subcmd == "tail":
            log = ctx.job.tail(ctx.args.unit, lines=ctx.args.lines)
            return {"unit": ctx.args.unit, "log": log}
        if subcmd == "cancel":
            ctx.job.cancel(ctx.args.unit)
            return {"unit": ctx.args.unit, "ok": True}
        if subcmd == "wait":
            return ctx.job.wait(ctx.args.unit, timeout=ctx.args.timeout)
        if subcmd == "list":
            jobs = ctx.job.list_jobs()
            return {"jobs": jobs, "count": len(jobs)}
        return {}

    def render(self, result):
        # `job tail`: print the raw log.
        if set(result) == {"unit", "log"}:
            return result["log"].rstrip("\n")
        # `job run`: "started <unit>\nlog: <path>"
        if {"unit", "log"} <= set(result) and "label" in result:
            return f"started {result['unit']}\nlog: {result['log']}"
        return None


PLUGIN = JobPlugin()
