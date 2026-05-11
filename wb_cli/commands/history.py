"""``wb-cli history`` — historical data from wb-mqtt-db."""

from __future__ import annotations

import argparse

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class HistoryPlugin(BasePlugin):
    name = "history"
    help = "historical data: time-series values and Mermaid charts"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Query historical data from wb-mqtt-db.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser("get", help="get time-series data for a channel")
        p.add_argument("channel", help="device/control (e.g. wb-adc/A1)")
        p.add_argument("--from", dest="from_ts", help="start time (ISO-8601)")
        p.add_argument("--to", dest="to_ts", help="end time (ISO-8601)")
        p.add_argument(
            "--limit",
            type=int,
            default=1000,
            help="max rows (default: 1000)",
        )
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("chart", help="Mermaid xychart for a channel")
        p.add_argument("channel", help="device/control")
        p.add_argument("--from", dest="from_ts", help="start time")
        p.add_argument("--to", dest="to_ts", help="end time")
        p.add_argument("--limit", type=int, default=100)
        p.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:
        if ctx.args.subcmd == "get":
            return self._get(ctx)
        if ctx.args.subcmd == "chart":
            return self._chart(ctx)
        return {}

    def _get(self, ctx) -> dict:
        params = _build_params(ctx)
        result = ctx.rpc.call(
            "db_logger/history/get_values",
            params,
        )
        values = result if isinstance(result, list) else result.get("values", [])
        return {
            "channel": ctx.args.channel,
            "values": values,
            "count": len(values),
        }

    def _chart(self, ctx) -> dict:
        params = _build_params(ctx)
        result = ctx.rpc.call(
            "db_logger/history/get_values",
            params,
        )
        values = result if isinstance(result, list) else result.get("values", [])
        if not values:
            raise WbCliError(
                code="HISTORY_CHANNEL_NOT_FOUND",
                message=f"No data for channel '{ctx.args.channel}'",
                details={"channel": ctx.args.channel},
                exit_code=ExitCode.DOMAIN,
            )
        chart = _mermaid_chart(ctx.args.channel, values)
        return {
            "channel": ctx.args.channel,
            "mermaid": chart,
            "point_count": len(values),
        }


def _build_params(ctx) -> dict:
    params: dict = {
        "channels": [_split_channel(ctx.args.channel)],
        "limit": ctx.args.limit,
    }
    if ctx.args.from_ts:
        params["timestamp"] = {"gt": ctx.args.from_ts}
    if ctx.args.to_ts:
        params.setdefault("timestamp", {})["lt"] = ctx.args.to_ts
    return params


def _split_channel(channel: str) -> list:
    if "/" not in channel:
        raise WbCliError(
            code="HISTORY_INVALID_PERIOD",
            message=f"Channel must be device/control, got '{channel}'",
            details={"channel": channel},
            exit_code=ExitCode.DOMAIN,
        )
    device, _, control = channel.partition("/")
    return [device, control]


def _mermaid_chart(title: str, values: list) -> str:
    lines = [
        "xychart-beta",
        f'  title "{title}"',
        '  x-axis "time"',
        '  y-axis "value"',
    ]
    nums = []
    for entry in values:
        val = entry.get("v", entry.get("value", 0))
        try:
            nums.append(float(val))
        except (TypeError, ValueError):
            nums.append(0)
    lines.append("  line [" + ", ".join(str(v) for v in nums) + "]")
    return "\n".join(lines)


PLUGIN = HistoryPlugin()
