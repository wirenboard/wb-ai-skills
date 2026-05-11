"""``wb-cli cloud`` — Wiren Board cloud agent status."""

from __future__ import annotations

import argparse

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin

_CLOUD_UNIT = "wb-cloud-agent@wirenboard.cloud"


class CloudPlugin(BasePlugin):
    name = "cloud"
    help = "Wiren Board cloud agent: link status and connection info"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Show cloud agent link status.",
        )
        parser.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:
        try:
            unit_status = ctx.systemd.status(_CLOUD_UNIT)
        except WbCliError as exc:
            raise WbCliError(
                code="CLOUD_AGENT_DOWN",
                message="wb-cloud-agent service not found or not running",
                hint="Run: wb-cli systemd start wb-cloud-agent@wirenboard.cloud",
                exit_code=ExitCode.ENVIRONMENT,
            ) from exc

        active = unit_status.get("ActiveState", "unknown")
        if active != "active":
            raise WbCliError(
                code="CLOUD_AGENT_DOWN",
                message=f"wb-cloud-agent is {active}",
                hint="Run: wb-cli systemd start wb-cloud-agent@wirenboard.cloud",
                details={"active_state": active},
                exit_code=ExitCode.ENVIRONMENT,
            )

        return {
            "service": _CLOUD_UNIT,
            "active_state": active,
            "sub_state": unit_status.get("SubState", "unknown"),
        }


PLUGIN = CloudPlugin()
