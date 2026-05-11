"""``wb-cli serial-debug`` — RS-485 bus debug capture."""

from __future__ import annotations

import argparse
import time

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.progress import countdown
from wb_cli.plugin import BasePlugin


class SerialDebugPlugin(BasePlugin):
    name = "serial-debug"
    help = "turn on RS-485 debug logging, capture for N seconds, then restore"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "Toggle wb-mqtt-serial's Debug control on, wait `--seconds`, then collect\n"
                "everything wb-mqtt-serial wrote to the journal during that window. The\n"
                "Debug control is restored to off even if the capture itself fails."
            ),
            epilog=("Example:\n" "  wb-cli serial-debug --port /dev/ttyRS485-1 --seconds 30\n"),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("--port", required=True, help="serial port path, e.g. /dev/ttyRS485-1")
        parser.add_argument(
            "--seconds",
            type=int,
            default=10,
            help="how long to keep debug on / collect the journal (default: 10)",
        )

    def dispatch(self, ctx) -> dict:
        port = ctx.args.port
        seconds = ctx.args.seconds

        try:
            ctx.mqtt.publish("/devices/wb-mqtt-serial/controls/Debug/on", "1")
        except WbCliError as exc:
            raise WbCliError(
                code="SERIAL_DEBUG_BUSY",
                message="Failed to enable serial debug mode",
                details={"port": port, "error": str(exc)},
                exit_code=ExitCode.ENVIRONMENT,
            ) from exc

        start_ts = time.time()
        try:
            countdown(f"capturing {port}", seconds)
            entries = ctx.journal.read(
                unit="wb-mqtt-serial",
                # journald accepts local time; we pin to UTC for reproducibility.
                since=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(start_ts)),
                timeout=10.0,
            )
        finally:
            try:
                ctx.mqtt.publish("/devices/wb-mqtt-serial/controls/Debug/on", "0")
            except WbCliError:
                ctx.log.warning("Failed to restore debug=false")

        return {
            "port": port,
            "capture_seconds": seconds,
            "entries": entries,
            "count": len(entries),
        }


PLUGIN = SerialDebugPlugin()
