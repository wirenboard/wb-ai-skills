"""``wb-cli serial-debug`` — RS-485 bus debug capture."""

from __future__ import annotations

import argparse

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class SerialDebugPlugin(BasePlugin):
    name = "serial-debug"
    help = "RS-485 bus debug: enable debug logging, capture, then restore"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Enable wb-mqtt-serial debug, capture for N seconds, restore.",
        )
        parser.add_argument(
            "--port",
            required=True,
            help="serial port path (e.g. /dev/ttyRS485-1)",
        )
        parser.add_argument(
            "--seconds",
            type=int,
            default=10,
            help="capture duration (default: 10)",
        )
        parser.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:
        port = ctx.args.port
        seconds = ctx.args.seconds

        # Enable debug via MQTT
        try:
            ctx.mqtt.publish(
                "/devices/wb-mqtt-serial/controls/Debug/on",
                "1",
            )
        except WbCliError as exc:
            raise WbCliError(
                code="SERIAL_DEBUG_BUSY",
                message="Failed to enable serial debug mode",
                details={"port": port, "error": str(exc)},
                exit_code=ExitCode.ENVIRONMENT,
            ) from exc

        ctx.log.info(f"Capturing debug on {port} for {seconds}s...")

        # Capture journal for wb-mqtt-serial
        try:
            entries = ctx.journal.read(
                unit="wb-mqtt-serial",
                lines=500,
                timeout=float(seconds + 5),
            )
        finally:
            # Restore debug off
            try:
                ctx.mqtt.publish(
                    "/devices/wb-mqtt-serial/controls/Debug/on",
                    "0",
                )
            except WbCliError:
                ctx.log.warning("Failed to restore debug=false")

        return {
            "port": port,
            "capture_seconds": seconds,
            "entries": entries,
            "count": len(entries),
        }


PLUGIN = SerialDebugPlugin()
