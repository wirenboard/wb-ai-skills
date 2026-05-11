"""``wb-cli job`` — managed background tasks."""

from __future__ import annotations

import argparse

from wb_cli.plugin import BasePlugin


class JobPlugin(BasePlugin):
    name = "job"
    help = "run long-running commands in the background, watch them, fetch logs"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "A thin wrapper over `systemd-run --collect` for long operations.\n"
                "Each job gets a unit name, a script file, and a log under\n"
                "/mnt/data/ai/wb-cli/jobs/. Use this for `apt upgrade`, backup tars,\n"
                "anything that would time out a normal SSH call."
            ),
            epilog=(
                "Examples:\n"
                "  unit=$(wb-cli --json job run upgrade 'apt-get -y upgrade' | jq -r .data.unit)\n"
                "  wb-cli job status $unit\n"
                "  wb-cli job tail   $unit -n 200\n"
                "  wb-cli job wait   $unit\n"
                "  wb-cli job list\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser(
            "run",
            help="start a shell command as a transient systemd unit",
            description="Create wb-cli-job-<label>-<ts>.service and run <command> inside it.",
        )
        p.add_argument("label", help="short label included in the unit name")
        p.add_argument("command", help="shell command line; quote if it contains spaces")

        p = sub.add_parser("status", help="show whether a job is active/inactive/failed")
        p.add_argument("unit", help="job unit name (from `job run` / `job list`)")

        p = sub.add_parser("tail", help="print the tail of a job's log")
        p.add_argument("unit", help="job unit name")
        p.add_argument("-n", "--lines", type=int, default=50, help="how many trailing lines (default: 50)")

        p = sub.add_parser("cancel", help="stop a running job")
        p.add_argument("unit", help="job unit name")

        p = sub.add_parser(
            "wait",
            help="block until a job finishes (or timeout)",
            description="Poll `systemctl is-active` until the unit is inactive, with a spinner on TTY.",
        )
        p.add_argument("unit", help="job unit name")
        p.add_argument(
            "--timeout",
            type=float,
            default=300.0,
            help="max wait in seconds (default: 300)",
        )

        sub.add_parser("list", help="list jobs we still have files for")

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
        # `job tail`: dump the raw log.
        if set(result) == {"unit", "log"}:
            return result["log"].rstrip("\n")
        # `job run`: "started <unit>\nlog: <path>"
        if {"unit", "log", "label"} <= set(result):
            return f"started {result['unit']}\nlog: {result['log']}"
        return None


PLUGIN = JobPlugin()
