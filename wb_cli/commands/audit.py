"""``wb-cli audit`` — quick system health check."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from wb_cli.plugin import BasePlugin


class AuditPlugin(BasePlugin):
    name = "audit"
    help = "quick health check (failed units, identity)"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "Quick controller health snapshot — what `wb-cli snapshot` saves, but\n"
                "with explicit per-check verdicts. Returns ok=false (exit 0 still) if\n"
                "any check fails."
            ),
        )

    def dispatch(self, ctx) -> dict:
        checks: List[Dict[str, Any]] = []

        # Failed units
        failed = ctx.systemd.list_failed()
        checks.append(
            {
                "check": "failed_units",
                "ok": len(failed) == 0,
                "count": len(failed),
                "units": [u.get("unit", u.get("UNIT", "")) for u in failed],
            }
        )

        # Controller identity
        info = ctx.controller.to_dict()
        checks.append(
            {
                "check": "controller_identity",
                "ok": info.get("serial_number") is not None,
                "serial_number": info.get("serial_number"),
                "release_name": info.get("release_name"),
            }
        )

        all_ok = all(c["ok"] for c in checks)
        return {
            "ok": all_ok,
            "checks": checks,
        }

    def render(self, result):
        verdict = "OK" if result.get("ok") else "FAIL"
        lines = [f"audit: {verdict}"]
        for chk in result.get("checks", []):
            mark = "ok" if chk.get("ok") else "fail"
            extras = []
            if chk["check"] == "failed_units" and chk.get("units"):
                extras.append(", ".join(chk["units"]))
            if chk["check"] == "controller_identity" and chk.get("serial_number"):
                extras.append(f"SN {chk['serial_number']}, release {chk.get('release_name', '?')}")
            tail = f" — {' | '.join(extras)}" if extras else ""
            lines.append(f"  [{mark}] {chk['check']}{tail}")
        return "\n".join(lines)


PLUGIN = AuditPlugin()
