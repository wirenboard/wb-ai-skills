"""``wb-cli cloud`` — Wiren Board cloud agent status."""

from __future__ import annotations

import argparse

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin

_CLOUD_UNIT = "wb-cloud-agent@wirenboard.cloud"


class CloudPlugin(BasePlugin):
    name = "cloud"
    help = "report whether the Wiren Board cloud agent is up"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                f"Check the state of the {_CLOUD_UNIT} systemd unit. Returns an\n"
                "error envelope if the agent is missing or inactive."
            ),
        )

    def dispatch(self, ctx) -> dict:
        try:
            unit_status = ctx.systemd.status(_CLOUD_UNIT)
        except WbCliError as exc:
            raise WbCliError(
                code="CLOUD_AGENT_DOWN",
                message="wb-cloud-agent service not found or not running",
                hint=f"Run: systemctl start {_CLOUD_UNIT}",
                exit_code=ExitCode.ENVIRONMENT,
            ) from exc

        active = unit_status.get("ActiveState", "unknown")
        if active != "active":
            raise WbCliError(
                code="CLOUD_AGENT_DOWN",
                message=f"wb-cloud-agent is {active}",
                hint=f"Run: systemctl start {_CLOUD_UNIT}",
                details={"active_state": active},
                exit_code=ExitCode.ENVIRONMENT,
            )

        return {
            "service": _CLOUD_UNIT,
            "active_state": active,
            "sub_state": unit_status.get("SubState", "unknown"),
        }


PLUGIN = CloudPlugin()
