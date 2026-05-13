"""``wb-cli mqtt-debug`` — verbose mosquitto logging.

Toggle mosquitto's ``log_type all`` via a drop-in
``/etc/mosquitto/conf.d/debug-verbose.conf`` and capture the resulting
``Received PUBLISH …`` journal entries as structured records.

Short captures (<= 600 s) run inline with a countdown. For long captures —
hours, days — pass ``--background --output <path>``; the plugin schedules
itself through ``wb-cli job run`` and the JSON envelope is written to the
output file when the job finishes.
"""

# pylint: disable=duplicate-code
# The plugin class shape (name/help/auto_spinner + register/subparsers/...)
# is identical across every wb-cli plugin — that's the plugin contract.

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib import mqtt_log
from wb_cli.lib.progress import countdown
from wb_cli.plugin import BasePlugin

_DEBUG_CONFIG_PATH = Path("/etc/mosquitto/conf.d/debug-verbose.conf")
_DEBUG_CONFIG_CONTENT = """\
# wb-cli mqtt-debug: verbose logging for PUBLISH diagnostics
log_type all
log_timestamp true
"""
_MOSQUITTO_UNIT = "mosquitto"
_RESTART_SETTLE_S = 1.0
_INLINE_MAX_SECONDS = 600


class MqttDebugPlugin(BasePlugin):  # pylint: disable=duplicate-code
    """Argparse boilerplate (register / subparsers / add_parser) is structurally
    similar to other plugins; that's the plugin contract, not a refactor target.
    """

    name = "mqtt-debug"
    help = "verbose mosquitto logging: enable / disable / status / capture"
    # `capture` draws its own countdown; the other subcommands are quick.
    auto_spinner = False

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "Toggle mosquitto verbose logging and capture structured PUBLISH\n"
                "records from the journal. Useful for tracing which client wrote\n"
                "to a given /devices/<id>/controls/<id> topic, or what wb-rules\n"
                "actually published.\n"
                "\n"
                "Verbose mode is implemented as a confed-style drop-in:\n"
                f"  {_DEBUG_CONFIG_PATH}  with `log_type all`\n"
                "Each toggle restarts mosquitto (≤1 s downtime; WB services on\n"
                "the Unix socket survive it)."
            ),
            epilog=(
                "Examples:\n"
                "  wb-cli mqtt-debug enable                        # turn on, leave on\n"
                "  wb-cli mqtt-debug disable                       # turn off\n"
                "  wb-cli mqtt-debug status\n"
                "  wb-cli mqtt-debug capture --seconds 60          # short inline capture\n"
                "  wb-cli mqtt-debug capture --seconds 60 \\\n"
                "      --topic '/devices/wb-mr6c_7' --source wb-rules\n"
                "  # long captures (hours/days) — run as a job, write JSON to disk:\n"
                "  wb-cli mqtt-debug capture --seconds 3600 --background \\\n"
                "      --output /mnt/data/ai/wb-cli/mqtt-debug-$(date +%s).json\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        sub.add_parser(
            "enable",
            help="enable verbose logging (drop-in conf + mosquitto restart)",
            description=(
                f"Write {_DEBUG_CONFIG_PATH} with ``log_type all`` and restart "
                "mosquitto. Already-enabled state is reported, not re-applied."
            ),
        )
        sub.add_parser(
            "disable",
            help="disable verbose logging (remove drop-in + mosquitto restart)",
            description=(
                f"Remove {_DEBUG_CONFIG_PATH} (if present) and restart mosquitto. "
                "Already-disabled state is reported, not re-applied."
            ),
        )
        sub.add_parser(
            "status",
            help="show whether verbose logging is on and mosquitto is active",
        )

        cap = sub.add_parser(
            "capture",
            help="capture PUBLISH records for N seconds, return structured JSON",
            description=(
                "Enable verbose logging (if needed), wait ``--seconds``, parse the\n"
                "journal entries published during the window, then restore the\n"
                "previous on/off state (only if we toggled it). ``--seconds`` up\n"
                f"to {_INLINE_MAX_SECONDS} runs inline; longer captures require\n"
                "``--background`` + ``--output``.\n"
                "\n"
                "``--topic`` and ``--source`` are substring filters applied to the\n"
                "parsed records (LLMs can also filter the JSON via ``jq``)."
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        cap.add_argument(
            "--seconds",
            type=int,
            default=30,
            help="capture window in seconds (default: 30)",
        )
        cap.add_argument("--topic", default=None, help="substring filter on the topic name")
        cap.add_argument("--source", default=None, help="substring filter on the client id")
        cap.add_argument(
            "--output",
            default=None,
            help="write the JSON envelope to this file (required with --background)",
        )
        cap.add_argument(
            "--background",
            action="store_true",
            help=(
                f"long capture (seconds > {_INLINE_MAX_SECONDS}): run via `wb-cli "
                "job run` and write the JSON envelope to --output on completion"
            ),
        )
        cap.add_argument(
            "--keep-enabled",
            action="store_true",
            help="do not restore verbose logging to its previous state after the capture",
        )

    def dispatch(self, ctx) -> dict:
        subcmd = ctx.args.subcmd
        if subcmd == "enable":
            return _enable(ctx)
        if subcmd == "disable":
            return _disable(ctx)
        if subcmd == "status":
            return _status(ctx)
        if subcmd == "capture":
            return _capture(ctx)
        return {}

    def render(self, result):
        if "entries" in result and "count" in result:
            return _render_capture(result)
        if "unit" in result and "output" in result:
            return f"capture started in background: {result['unit']}\noutput: {result['output']}"
        if "verbose_enabled" in result:
            return _render_status(result)
        if "ok" in result and "action" in result:
            return f"ok  mqtt-debug {result['action']}: verbose={result['verbose_enabled']}"
        return None


# --------------------------------------------------------------------------- #
# enable / disable / status
# --------------------------------------------------------------------------- #


def _is_enabled() -> bool:
    return _DEBUG_CONFIG_PATH.exists()


def _enable(ctx) -> dict:
    if _is_enabled():
        return {
            "action": "enable",
            "ok": True,
            "verbose_enabled": True,
            "changed": False,
        }
    _write_debug_config()
    ctx.systemd.restart(_MOSQUITTO_UNIT)
    return {
        "action": "enable",
        "ok": True,
        "verbose_enabled": True,
        "changed": True,
    }


def _disable(ctx) -> dict:
    if not _is_enabled():
        return {
            "action": "disable",
            "ok": True,
            "verbose_enabled": False,
            "changed": False,
        }
    _DEBUG_CONFIG_PATH.unlink()
    ctx.systemd.restart(_MOSQUITTO_UNIT)
    return {
        "action": "disable",
        "ok": True,
        "verbose_enabled": False,
        "changed": True,
    }


def _status(ctx) -> dict:
    enabled = _is_enabled()
    try:
        unit_status = ctx.systemd.status(_MOSQUITTO_UNIT)
        active_state = unit_status.get("ActiveState", "unknown")
    except WbCliError:
        active_state = "unknown"
    return {
        "verbose_enabled": enabled,
        "config_path": str(_DEBUG_CONFIG_PATH),
        "mosquitto_active_state": active_state,
    }


def _write_debug_config() -> None:
    try:
        _DEBUG_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DEBUG_CONFIG_PATH.write_text(_DEBUG_CONFIG_CONTENT, encoding="utf-8")
    except PermissionError as exc:
        raise WbCliError(
            code="MQTT_DEBUG_PERMISSION",
            message=f"Cannot write {_DEBUG_CONFIG_PATH}: {exc}",
            hint="Run as root (sudo or the controller's wb-cli) — mosquitto config is root-owned.",
            exit_code=ExitCode.ENVIRONMENT,
        ) from exc


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #


def _capture(ctx) -> dict:  # pylint: disable=too-many-locals
    args = ctx.args
    seconds = args.seconds
    if seconds <= 0:
        raise WbCliError(
            code="MQTT_DEBUG_INVALID_SECONDS",
            message="--seconds must be positive",
            exit_code=ExitCode.USAGE,
        )

    if args.background:
        return _capture_background(ctx)

    if seconds > _INLINE_MAX_SECONDS:
        raise WbCliError(
            code="MQTT_DEBUG_TOO_LONG",
            message=(
                f"--seconds {seconds} exceeds the inline cap of {_INLINE_MAX_SECONDS}s. "
                "For long captures use --background --output <path>."
            ),
            hint=(
                "wb-cli mqtt-debug capture --seconds N --background "
                "--output /mnt/data/ai/wb-cli/mqtt-debug.json"
            ),
            exit_code=ExitCode.USAGE,
        )

    was_enabled = _is_enabled()
    we_enabled_it = False
    if not was_enabled:
        _write_debug_config()
        ctx.systemd.restart(_MOSQUITTO_UNIT)
        we_enabled_it = True
        # Give mosquitto a beat to start writing the new log_type setting.
        time.sleep(_RESTART_SETTLE_S)

    start_ts = time.time()
    try:
        countdown(f"capturing mqtt for {seconds}s", seconds)
        entries = ctx.journal.read(
            unit=_MOSQUITTO_UNIT,
            since=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(start_ts)),
            timeout=30.0,
        )
        parsed = mqtt_log.parse_entries(
            entries,
            topic=args.topic,
            source=args.source,
        )
    finally:
        if we_enabled_it and not args.keep_enabled:
            try:
                _DEBUG_CONFIG_PATH.unlink(missing_ok=True)
                ctx.systemd.restart(_MOSQUITTO_UNIT)
            except (WbCliError, OSError) as exc:  # pylint: disable=broad-except
                ctx.log.warning(f"failed to restore mqtt-debug off: {exc}")

    result = {
        "seconds": seconds,
        "entries": parsed,
        "count": len(parsed),
        "topic_filter": args.topic,
        "source_filter": args.source,
        "verbose_was_already_enabled": was_enabled,
    }
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps({"data": result}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["output"] = str(args.output)
    return result


def _capture_background(ctx) -> dict:
    args = ctx.args
    if not args.output:
        raise WbCliError(
            code="MQTT_DEBUG_OUTPUT_REQUIRED",
            message="--background requires --output PATH",
            hint=(
                "Write the long-capture JSON to a file under /mnt/data, "
                "e.g. --output /mnt/data/ai/wb-cli/mqtt-debug-$(date +%s).json"
            ),
            exit_code=ExitCode.USAGE,
        )
    parts = ["wb-cli", "--json", "mqtt-debug", "capture", "--seconds", str(args.seconds)]
    if args.topic:
        parts += ["--topic", args.topic]
    if args.source:
        parts += ["--source", args.source]
    if args.keep_enabled:
        parts.append("--keep-enabled")
    parts += ["--output", args.output]
    # Pipe stdout to /dev/null — the JSON envelope lives in --output, the job
    # log only needs stderr (countdown / warnings).
    command = " ".join(parts) + " >/dev/null"
    info = ctx.job.run("mqtt-debug-capture", command)
    return {
        "action": "capture",
        "background": True,
        "seconds": args.seconds,
        "output": args.output,
        "unit": info["unit"],
        "log": info["log"],
    }


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def _render_status(result: dict) -> str:
    return (
        f"verbose_enabled  {str(result['verbose_enabled']).lower()}\n"
        f"config_path      {result['config_path']}\n"
        f"mosquitto        {result['mosquitto_active_state']}"
    )


def _render_capture(result: dict) -> str:
    entries = result.get("entries") or []
    header = f"captured {result['count']} PUBLISH(s) in {result['seconds']}s" f"{_filter_suffix(result)}"
    if not entries:
        return header + "\n(no matching messages — try a longer --seconds or relax filters)"
    rows = []
    for entry in entries:
        rows.append(
            {
                "time": (entry.get("timestamp") or "")[11:19] or "?",
                "source": entry.get("source", "?"),
                "topic": entry.get("topic", "?"),
                "qos": str(entry.get("qos", "?")),
                "retain": "r" if entry.get("retain") else "-",
                "size": str(entry.get("payload_size", "?")),
            }
        )
    columns = ["time", "source", "topic", "qos", "retain", "size"]
    widths = {c: max(len(c), *(len(r[c]) for r in rows)) for c in columns}
    line = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    body = ["  ".join(r[c].ljust(widths[c]) for c in columns) for r in rows]
    return "\n".join([header, line, sep, *body])


def _filter_suffix(result: dict) -> str:
    parts = []
    if result.get("topic_filter"):
        parts.append(f"topic~{result['topic_filter']}")
    if result.get("source_filter"):
        parts.append(f"source~{result['source_filter']}")
    return f"  [{', '.join(parts)}]" if parts else ""


PLUGIN = MqttDebugPlugin()
