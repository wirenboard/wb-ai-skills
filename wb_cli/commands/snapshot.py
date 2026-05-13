"""``wb-cli snapshot`` — save / diff system state snapshots."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Iterator, List, Tuple

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

    def render(self, result):
        if "changes" in result and "baseline" in result:
            return _render_diff(result)
        return None

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


def _render_diff(result: dict) -> str:
    """Render snapshot diff as a flat ``key: old → new`` list.

    Walks each top-level change recursively and emits one line per leaf
    that actually changed — instead of dumping whole nested JSON blobs
    side by side. Lists are shown by added/removed items.
    """
    changes = result.get("changes", [])
    if not changes:
        return f"no changes vs {result.get('baseline', '?')}"
    lines: List[str] = [f"diff vs {result.get('baseline', '?')} — {len(changes)} top-level key(s) changed:"]
    leaves: List[Tuple[str, Any, Any]] = []
    for change in changes:
        leaves.extend(_walk_leaves(change["key"], change["old"], change["new"]))
    if not leaves:
        # All top-level changes resolved to noop (shouldn't happen, but guard).
        return lines[0]
    width = max(len(path) for path, _, _ in leaves)
    for path, old_val, new_val in leaves:
        lines.append(f"  {path.ljust(width)}  {_fmt(old_val)} → {_fmt(new_val)}")
    return "\n".join(lines)


def _walk_leaves(path: str, old: Any, new: Any) -> Iterator[Tuple[str, Any, Any]]:
    """Yield ``(path, old_leaf, new_leaf)`` for every actual difference."""
    if old == new:
        return
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            yield from _walk_leaves(f"{path}.{key}", old.get(key), new.get(key))
        return
    if isinstance(old, list) and isinstance(new, list):
        # For lists we report added / removed entries; order changes are noisy.
        old_set, new_set = list(old), list(new)
        added = [x for x in new_set if x not in old_set]
        removed = [x for x in old_set if x not in new_set]
        for item in removed:
            yield (f"{path}[-]", item, None)
        for item in added:
            yield (f"{path}[+]", None, item)
        return
    yield (path, old, new)


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


PLUGIN = SnapshotPlugin()
