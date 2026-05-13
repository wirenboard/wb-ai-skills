"""``wb-cli history`` — historical data from wb-mqtt-db."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class HistoryPlugin(BasePlugin):
    name = "history"
    help = "time-series history of a control's values"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "Read recorded values of a control from wb-mqtt-db. The channel is\n"
                "addressed in wb-rules style: `<device>/<control>` (same as `dev`)."
            ),
            epilog=("Examples:\n" "  wb-cli history get   wb-map6s_34/P\\ 1 --limit 50\n"),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser(
            "get",
            help="rows of (timestamp, value)",
            description="Return raw rows; pipe through jq for ad-hoc filtering.",
        )
        p.add_argument("channel", help="<device>/<control>, e.g. wb-adc/A1")
        p.add_argument("--from", dest="from_ts", help="start time (ISO-8601 or what db_logger accepts)")
        p.add_argument("--to", dest="to_ts", help="end time (ISO-8601)")
        p.add_argument(
            "--limit",
            type=int,
            default=1000,
            help="max rows (default: 1000)",
        )

    def dispatch(self, ctx) -> dict:
        if ctx.args.subcmd == "get":
            return self._get(ctx)
        return {}

    def _get(self, ctx) -> dict:
        params = _build_params(ctx)
        result = ctx.rpc.call("db_logger/history/get_values", params)
        values = result if isinstance(result, list) else result.get("values", [])
        return {
            "channel": ctx.args.channel,
            "values": values,
            "count": len(values),
        }


def _build_params(ctx) -> dict:
    params: dict = {
        "channels": [_split_channel(ctx.args.channel)],
        "limit": ctx.args.limit,
    }
    timestamp: dict = {}
    if ctx.args.from_ts:
        timestamp["gt"] = _parse_ts(ctx.args.from_ts, "--from")
    if ctx.args.to_ts:
        timestamp["lt"] = _parse_ts(ctx.args.to_ts, "--to")
    if timestamp:
        params["timestamp"] = timestamp
    return params


def _parse_ts(value: str, flag: str) -> int:
    """Parse an ISO-8601 datetime string into a Unix timestamp (seconds)."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise WbCliError(
            code="HISTORY_INVALID_TIMESTAMP",
            message=f"Cannot parse {flag} value '{value}' as ISO-8601 datetime",
            hint="Use format: 2026-05-11T00:00:00 or 2026-05-11 00:00:00",
            details={"value": value, "flag": flag},
            exit_code=ExitCode.USAGE,
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _split_channel(channel: str) -> list:
    if "/" not in channel:
        raise WbCliError(
            code="HISTORY_INVALID_CHANNEL",
            message=f"Channel must be <device>/<control>, got '{channel}'",
            details={"channel": channel},
            exit_code=ExitCode.USAGE,
        )
    device, _, control = channel.partition("/")
    return [device, control]


PLUGIN = HistoryPlugin()
