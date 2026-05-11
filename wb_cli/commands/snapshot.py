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
    help = "system state snapshots: save current state, diff against baseline"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Save or compare system state snapshots.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser("save", help="save a snapshot of current state")
        p.add_argument("--label", help="optional label for the snapshot")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("diff", help="diff current state against a saved snapshot")
        p.add_argument("path", help="path to baseline snapshot file")
        p.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:
        if ctx.args.subcmd == "save":
            return self._save(ctx)
        if ctx.args.subcmd == "diff":
            return self._diff(ctx)
        return {}

    def _save(self, ctx) -> dict:
        state = self._collect_state(ctx)
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        label = ctx.args.label or time.strftime("%Y%m%d-%H%M%S")
        path = _SNAPSHOT_DIR / f"{label}.json"
        path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"path": str(path), "label": label}

    def _diff(self, ctx) -> dict:
        baseline_path = Path(ctx.args.path)
        if not baseline_path.exists():
            raise WbCliError(
                code="AUDIT_BASELINE_NOT_FOUND",
                message=f"Baseline snapshot not found: {baseline_path}",
                details={"path": str(baseline_path)},
                exit_code=ExitCode.DOMAIN,
            )
        try:
            baseline = json.loads(
                baseline_path.read_text(encoding="utf-8"),
            )
        except json.JSONDecodeError as exc:
            raise WbCliError(
                code="AUDIT_INVALID_SNAPSHOT",
                message=f"Snapshot is not valid JSON: {exc}",
                details={"path": str(baseline_path)},
                exit_code=ExitCode.DOMAIN,
            ) from exc

        current = self._collect_state(ctx)
        changes = _compute_diff(baseline, current)
        return {
            "baseline": str(baseline_path),
            "changes": changes,
            "change_count": len(changes),
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
            changes.append(
                {
                    "key": key,
                    "old": old_val,
                    "new": new_val,
                }
            )
    return changes


PLUGIN = SnapshotPlugin()
