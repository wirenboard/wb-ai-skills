"""``wb-cli modbus-fw`` — firmware update of Modbus / RS-485 devices.

Wraps the ``wb-device-manager/fw-update/*`` RPC: check available firmware,
start an update, restore a device stuck in bootloader after a failed update,
clear a leftover error from the state topic, and watch live progress.

The wb-device-manager service does the heavy lifting (downloads the binary,
flashes via Modbus bootloader, publishes progress to
``/wb-device-manager/firmware_update/state``). We expose it as a CLI.
"""

# pylint: disable=duplicate-code
# _open_state_stream / _reap mirror the modbus.scan helpers — same dance of
# Popen-mosquitto_sub-on-state plus graceful reap. Sharing them via lib would
# pull a streaming helper into a place that doesn't really want one.

from __future__ import annotations

import argparse
import json
import subprocess
import time

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.progress import ProgressBar
from wb_cli.plugin import BasePlugin

_STATE_TOPIC = "/wb-device-manager/firmware_update/state"


class ModbusFwPlugin(BasePlugin):
    name = "modbus-fw"
    help = "firmware update of Modbus devices (check, update, restore, watch)"
    # `watch` and `update --wait` draw their own progress; others are quick.
    auto_spinner = False

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "Update the firmware of Wiren Board Modbus devices over RS-485.\n"
                "Same flow the web UI's 'Check / Update' buttons trigger — backed by\n"
                "wb-device-manager's fw-update RPC.\n"
                "\n"
                "Typical use:\n"
                "  1. `wb-cli modbus-fw check 4 --port /dev/ttyRS485-1`   # what's available\n"
                "  2. `wb-cli modbus-fw update 4 --port /dev/ttyRS485-1`  # start flashing\n"
                "  3. `wb-cli modbus-fw watch`                            # live progress\n"
                "  4. on a failed update: `wb-cli modbus-fw restore 4 --port ...`"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        for action, helpline in [
            ("check", "show current and available firmware/bootloader versions"),
            ("update", "flash the latest firmware (device must be reachable)"),
            ("restore", "re-flash a device stuck in bootloader after a failed update"),
            ("clear-error", "remove a stale error entry from the state topic"),
        ]:
            sp = sub.add_parser(action, help=helpline)
            _add_target_args(sp)
            if action == "update":
                sp.add_argument(
                    "--type",
                    dest="software_type",
                    choices=("firmware", "bootloader"),
                    default="firmware",
                    help="which component to flash (default: firmware)",
                )
                sp.add_argument(
                    "--wait",
                    action="store_true",
                    help="block until the update finishes or fails (draws a progress bar)",
                )
            elif action == "restore":
                sp.add_argument(
                    "--wait",
                    action="store_true",
                    help="block until restore finishes",
                )
            elif action == "clear-error":
                sp.add_argument(
                    "--type",
                    dest="software_type",
                    choices=("firmware", "bootloader"),
                    default="firmware",
                    help="which component's error to clear (default: firmware)",
                )

        sp = sub.add_parser(
            "watch",
            help="stream the firmware-update state topic until everything settles",
            description=(
                "Subscribe to /wb-device-manager/firmware_update/state and print updates"
                " until every entry reports progress=100 or carries an error."
            ),
        )
        sp.add_argument(
            "--timeout",
            type=float,
            default=600.0,
            help="give up after this many seconds (default: 600)",
        )

        sp = sub.add_parser(
            "state",
            help="print the current firmware-update state once and exit",
            description="One-shot read of the retained state topic.",
        )

    def dispatch(self, ctx) -> dict:  # pylint: disable=too-many-return-statements
        subcmd = ctx.args.subcmd
        if subcmd == "check":
            return _check(ctx)
        if subcmd == "update":
            return _update(ctx)
        if subcmd == "restore":
            return _restore(ctx)
        if subcmd == "clear-error":
            return _clear_error(ctx)
        if subcmd == "watch":
            return _watch(ctx)
        if subcmd == "state":
            return _state_once(ctx)
        return {}

    def render(self, result):  # pylint: disable=too-many-return-statements
        # `check`
        if "can_update" in result:
            verdict = "update available" if result["can_update"] else "up to date"
            lines = [
                f"{verdict}  (slave_id={result['slave_id']}, port={result['port']})",
                f"  firmware:   {result.get('fw', '?')} -> {result.get('available_fw', '?')}",
                f"  bootloader: {result.get('bootloader', '?')} -> {result.get('available_bootloader', '?')}",
            ]
            return "\n".join(lines)
        # `update` / `restore` / `clear-error`
        if "ok" in result and "slave_id" in result:
            return f"ok  {result['action']}  slave_id={result['slave_id']} port={result['port']}"
        # `watch` / `state`
        if "devices" in result:
            return _render_state(result)
        return None


# --------------------------------------------------------------------------- #
# argument helpers
# --------------------------------------------------------------------------- #


def _add_target_args(p):
    p.add_argument("slave_id", type=int, help="Modbus slave address, 1-247")
    p.add_argument("--port", required=True, help="serial port path, e.g. /dev/ttyRS485-1")
    p.add_argument("--baud", type=int, default=9600, help="baud rate (default: 9600)")
    p.add_argument("--parity", default="N", choices=("N", "E", "O"), help="parity (default: N)")
    p.add_argument("--data-bits", dest="data_bits", type=int, default=8, help="data bits (default: 8)")
    p.add_argument("--stop-bits", dest="stop_bits", type=int, default=2, help="stop bits (default: 2)")


def _port_arg(args) -> dict:
    return {
        "path": args.port,
        "baud_rate": args.baud,
        "parity": args.parity,
        "data_bits": args.data_bits,
        "stop_bits": args.stop_bits,
    }


# --------------------------------------------------------------------------- #
# RPC actions
# --------------------------------------------------------------------------- #


def _check(ctx) -> dict:
    args = ctx.args
    info = ctx.rpc.call(
        "wb-device-manager/fw-update/GetFirmwareInfo",
        {"slave_id": args.slave_id, "port": _port_arg(args)},
        timeout=20.0,
    )
    if not isinstance(info, dict):
        info = {}
    return {
        "slave_id": args.slave_id,
        "port": args.port,
        "fw": info.get("fw"),
        "available_fw": info.get("available_fw"),
        "can_update": bool(info.get("can_update")),
        "bootloader": info.get("bootloader"),
        "available_bootloader": info.get("available_bootloader"),
    }


def _update(ctx) -> dict:
    args = ctx.args
    ctx.rpc.call(
        "wb-device-manager/fw-update/Update",
        {
            "slave_id": args.slave_id,
            "port": _port_arg(args),
            "type": args.software_type,
        },
        timeout=15.0,
    )
    result = {
        "action": "update",
        "slave_id": args.slave_id,
        "port": args.port,
        "type": args.software_type,
        "ok": True,
    }
    if args.wait:
        result.update(_wait_for_completion(args.slave_id, args.port))
    return result


def _restore(ctx) -> dict:
    args = ctx.args
    ctx.rpc.call(
        "wb-device-manager/fw-update/Restore",
        {"slave_id": args.slave_id, "port": _port_arg(args)},
        timeout=15.0,
    )
    result = {
        "action": "restore",
        "slave_id": args.slave_id,
        "port": args.port,
        "ok": True,
    }
    if args.wait:
        result.update(_wait_for_completion(args.slave_id, args.port))
    return result


def _clear_error(ctx) -> dict:
    args = ctx.args
    ctx.rpc.call(
        "wb-device-manager/fw-update/ClearError",
        {
            "slave_id": args.slave_id,
            "port": _port_arg(args),
            "type": args.software_type,
        },
        timeout=10.0,
    )
    return {
        "action": "clear-error",
        "slave_id": args.slave_id,
        "port": args.port,
        "type": args.software_type,
        "ok": True,
    }


# --------------------------------------------------------------------------- #
# state / watch
# --------------------------------------------------------------------------- #


def _state_once(ctx) -> dict:
    try:
        msgs = ctx.mqtt.subscribe(_STATE_TOPIC, timeout=3.0)
    except WbCliError as exc:
        if exc.code == "MQTT_TIMEOUT":
            # An empty firmware-update state topic just means "nothing in flight".
            return {"devices": [], "count": 0}
        raise
    if not msgs:
        return {"devices": [], "count": 0}
    return _parse_state(msgs[-1][1])


def _watch(ctx) -> dict:
    """Stream the firmware-update state topic until everything settles."""
    deadline = time.monotonic() + ctx.args.timeout
    proc = _open_state_stream()
    last_state: dict = {"devices": [], "count": 0}
    with proc, ProgressBar("firmware updates") as progress_bar:
        try:
            while time.monotonic() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                state = _parse_state(line)
                last_state = state
                progress_bar.update(_overall_progress(state), suffix=_summary_for_bar(state))
                if _all_done(state):
                    break
        finally:
            _reap(proc)
    return last_state


def _wait_for_completion(slave_id: int, port: str) -> dict:
    """Block until the (slave_id, port) entry in the state topic finishes or errors."""
    deadline = time.monotonic() + 600.0
    proc = _open_state_stream()
    with proc, ProgressBar(f"flashing slave_id={slave_id}") as progress_bar:
        try:
            while time.monotonic() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                state = _parse_state(line)
                entry = _find_entry(state, slave_id, port)
                if entry is None:
                    continue
                progress_bar.update(entry.get("progress", 0), suffix=entry.get("type", ""))
                if entry.get("error"):
                    return {"final": "error", "error": entry["error"]}
                if entry.get("progress", 0) >= 100:
                    return {"final": "done"}
        finally:
            _reap(proc)
    return {"final": "timeout"}


def _open_state_stream():
    try:
        return subprocess.Popen(
            ["mosquitto_sub", "-t", _STATE_TOPIC, "-F", "%p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except FileNotFoundError as exc:
        raise WbCliError(  # pylint: disable=duplicate-code
            code="MQTT_BROKER_DOWN",
            message="mosquitto_sub not found; is mosquitto-clients installed?",
            exit_code=ExitCode.ENVIRONMENT,
        ) from exc


def _reap(proc) -> None:
    """Terminate a Popen safely with a kill fallback."""
    proc.terminate()
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        proc.kill()


# --------------------------------------------------------------------------- #
# parsing / rendering helpers
# --------------------------------------------------------------------------- #


def _parse_state(payload: str) -> dict:
    payload = (payload or "").strip()
    if not payload:
        return {"devices": [], "count": 0}
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return {"devices": [], "count": 0}
    devices = data if isinstance(data, list) else data.get("devices", [])
    return {"devices": devices, "count": len(devices)}


def _find_entry(state: dict, slave_id: int, port: str):
    for entry in state.get("devices", []):
        if entry.get("slave_id") == slave_id and entry.get("port", {}).get("path") == port:
            return entry
    return None


def _overall_progress(state: dict) -> int:
    devices = state.get("devices", [])
    if not devices:
        return 100
    return int(sum(d.get("progress", 0) for d in devices) / len(devices))


def _summary_for_bar(state: dict) -> str:
    devices = state.get("devices", [])
    errs = sum(1 for d in devices if d.get("error"))
    return f"{len(devices)} in flight, {errs} errored"


def _all_done(state: dict) -> bool:
    return all(d.get("progress", 0) >= 100 or d.get("error") for d in state.get("devices", []))


def _render_state(state: dict) -> str:
    devices = state.get("devices", [])
    if not devices:
        return "no firmware updates in flight"
    rows = []
    for d in devices:
        rows.append(
            {
                "slave_id": str(d.get("slave_id", "?")),
                "port": d.get("port", {}).get("path", "?"),
                "type": d.get("type", "?"),
                "progress": f"{d.get('progress', 0)}%",
                "status": (d.get("error") or {}).get("message") or "OK",
            }
        )
    columns = ["slave_id", "port", "type", "progress", "status"]
    widths = {col: max(len(col), *(len(r[col]) for r in rows)) for col in columns}
    header = "  ".join(col.ljust(widths[col]) for col in columns)
    sep = "  ".join("-" * widths[col] for col in columns)
    body = ["  ".join(r[col].ljust(widths[col]) for col in columns) for r in rows]
    return "\n".join([f"{len(rows)} update(s):", header, sep, *body])


PLUGIN = ModbusFwPlugin()
