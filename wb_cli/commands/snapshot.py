"""``wb-cli snapshot`` — save / diff system state snapshots."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin

_SNAPSHOT_DIR = Path("/mnt/data/ai/wb-cli/snapshots")


class SnapshotPlugin(BasePlugin):
    name = "snapshot"
    help = "save controller state to disk and compare snapshots later"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "Capture a small JSON snapshot of the controller state (identity +\n"
                "failed units) and diff against an earlier one. Useful around firmware\n"
                "updates, package upgrades, or any change you want to roll back from."
            ),
            epilog=(
                "Examples:\n"
                "  wb-cli snapshot save --label pre-upgrade\n"
                "  wb-cli snapshot diff /mnt/data/ai/wb-cli/snapshots/pre-upgrade.json\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser(
            "save",
            help="save a snapshot to /mnt/data/ai/wb-cli/snapshots/<label>.json",
            description="Write a JSON snapshot file. Label defaults to a UTC timestamp.",
        )
        p.add_argument("--label", help="filename stem; default: <YYYYmmdd-HHMMSS>")

        p = sub.add_parser(
            "diff",
            help="compare the current state against a baseline snapshot",
            description="Read <path>, collect the current state, and list per-key differences.",
        )
        p.add_argument("path", help="absolute path to a snapshot file")

    def dispatch(self, ctx) -> dict:
        if ctx.args.subcmd == "save":
            return self._save(ctx)
        if ctx.args.subcmd == "diff":
            return self._diff(ctx)
        return {}

    def _save(self, ctx) -> dict:
        state = self._collect_state(ctx)
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        label = ctx.args.label or time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        path = _SNAPSHOT_DIR / f"{label}.json"
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"path": str(path), "label": label, "ok": True}

    def _diff(self, ctx) -> dict:
        baseline_path = Path(ctx.args.path)
        if not baseline_path.exists():
            raise WbCliError(
                code="SNAPSHOT_BASELINE_NOT_FOUND",
                message=f"Baseline snapshot not found: {baseline_path}",
                details={"path": str(baseline_path)},
                exit_code=ExitCode.DOMAIN,
            )
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WbCliError(
                code="SNAPSHOT_INVALID",
                message=f"Snapshot is not valid JSON: {exc}",
                details={"path": str(baseline_path)},
                exit_code=ExitCode.DOMAIN,
            ) from exc

        current = self._collect_state(ctx)
        changes = _compute_diff(baseline, current)
        return {
            "baseline": str(baseline_path),
            "changes": changes,
            "count": len(changes),
        }

    def _collect_state(self, ctx) -> dict:
        return {
            "controller": ctx.controller.to_dict(),
            "failed_units": ctx.systemd.list_failed(),
        }


def _compute_diff(old: dict, new: dict) -> list:
    changes = []
    all_keys = sorted(set(list(old.keys()) + list(new.keys())))
    for key in all_keys:
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            changes.append({"key": key, "old": old_val, "new": new_val})
    return changes


PLUGIN = SnapshotPlugin()
