"""``wb-cli serial wb-fw`` — firmware update of WB Modbus devices.

Folded in from the standalone ``modbus-fw`` plugin in 1.8.0 — same logic
and arguments, same wb-device-manager fw-update RPC, just lives under
the ``serial`` plugin since firmware update is one more thing you do
over an RS-485 port. Exposed as a flat module here (no Plugin class);
``serial/_register.py`` wires the parsers, ``_actions.py`` dispatches.

Subcommands:
  * ``check``   — what firmware is available (one device, or every device
                  in /etc/wb-mqtt-serial.conf).
  * ``update``  — flash (single device, ``--all`` for a bulk pass, ``--wait``
                  or ``--background`` for long flashes).
  * ``restore`` — re-flash a device stuck in bootloader after a failed update.

In-flight progress / queue lives on the retained MQTT topic
``/wb-device-manager/firmware_update/state``.
"""

from __future__ import annotations

import argparse
import json
import shlex
import time

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib import serial_conf, serial_port
from wb_cli.lib.progress import ProgressBar

_STATE_TOPIC = "/wb-device-manager/firmware_update/state"


# --------------------------------------------------------------------------- #
# parser registration — called from ``serial/_register.py``
# --------------------------------------------------------------------------- #


def register_actions(sub: argparse._SubParsersAction) -> None:
    """Register ``check`` / ``update`` / ``restore`` onto the wb-fw sub-parser."""
    sp = sub.add_parser(
        "check",
        help="show available firmware (one device, or every device the scan finds)",
        description=(
            "Without slave_id: walk every device in /etc/wb-mqtt-serial.conf"
            " (optionally filtered by --port) and check each.\n"
            "With slave_id: check just that device."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_optional_target_args(sp)

    sp = sub.add_parser(
        "update",
        help="flash the latest firmware (one device, or `--all` everything updatable)",
        description=(
            "Without slave_id, requires --all (and either --port to limit the scope\n"
            "or no --port to update everything in flight): finds every device with\n"
            "``can_update=true`` and queues an update for each.\n"
            "With slave_id: update just that one device."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_optional_target_args(sp)
    sp.add_argument(
        "--all",
        action="store_true",
        help="(no slave_id) acknowledge bulk update of every updatable device",
    )
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
    sp.add_argument(
        "--background",
        action="store_true",
        help="run as a wb-cli job (for bulk / hours-long flashes); requires --output",
    )
    sp.add_argument(
        "--output",
        default=None,
        help="write the JSON envelope to this file (required with --background)",
    )

    sp = sub.add_parser(
        "restore",
        help="re-flash a device stuck in bootloader after a failed update",
    )
    _add_target_args(sp)
    sp.add_argument(
        "--wait",
        action="store_true",
        help="block until restore finishes",
    )


def _add_target_args(p):
    """slave_id required + UART overrides — used by ``restore``."""
    p.add_argument("slave_id", type=int, help="Modbus slave address, 1-247")
    _add_uart_args(p, require_port=True)


def _add_optional_target_args(p):
    """slave_id optional — used by ``check`` and ``update`` (bulk vs targeted)."""
    p.add_argument(
        "slave_id",
        type=int,
        nargs="?",
        default=None,
        help="Modbus slave address; omit to operate on every configured device",
    )
    _add_uart_args(p, require_port=False)


def _add_uart_args(p, *, require_port: bool):
    p.add_argument(
        "--port",
        required=require_port,
        help="serial port path, e.g. /dev/ttyRS485-1 (filters bulk mode to one port)",
    )
    serial_port.add_uart_args(p)


# --------------------------------------------------------------------------- #
# dispatch — called from ``serial/_actions.py``
# --------------------------------------------------------------------------- #


def dispatch(ctx) -> dict:
    action = getattr(ctx.args, "wb_fw_action", None)
    if action == "check":
        return _check(ctx)
    if action == "update":
        return _update(ctx)
    if action == "restore":
        return _restore(ctx)
    return {}


def render(result):
    """Render a wb-fw result for human mode. Returns ``None`` if not ours."""
    if "can_update" in result:
        return _render_check_one(result)
    if (
        "devices" in result
        and result["devices"]
        and ("can_update" in result["devices"][0] or "error" in result["devices"][0])
    ):
        return _render_check_bulk(result["devices"])
    if "queued" in result:
        return _render_update_bulk(result)
    if "unit" in result and "output" in result:
        return f"update started in background: {result['unit']}\noutput: {result['output']}"
    if "ok" in result and "slave_id" in result and result.get("action") in {"update", "restore"}:
        return f"ok  {result['action']}  slave_id={result['slave_id']} port={result['port']}"
    return None


# --------------------------------------------------------------------------- #
# RPC actions
# --------------------------------------------------------------------------- #


_port_arg = serial_port.port_params_from_args  # alias used in places below


def _check(ctx) -> dict:
    if ctx.args.slave_id is not None:
        port_str = ctx.args.port or "all ports"
        device_type = _lookup_device_type(ctx, ctx.args.slave_id, ctx.args.port)
        with ProgressBar(f"checking slave_id={ctx.args.slave_id}") as pb:
            pb.update(0, suffix=port_str)
            return _check_one(ctx, ctx.args.slave_id, _port_arg(ctx.args), device_type=device_type)
    content = serial_conf.load_config(ctx)
    targets = serial_conf.list_devices(content, port=ctx.args.port)
    total = len(targets)
    rows = []
    with ProgressBar("checking firmware") as pb:
        for i, dev in enumerate(targets):
            port_path = dev.get("port_path", dev.get("port", {}).get("path", ""))
            pb.update(
                int(i / total * 100) if total else 100,
                suffix=f"{i + 1}/{total}  slave_id={dev['slave_id']}  {port_path}",
            )
            rows.append(
                _check_one(
                    ctx,
                    dev["slave_id"],
                    dev["port"],
                    device_type=dev.get("device_type"),
                    _swallow=True,
                )
            )
    return {"devices": rows, "count": len(rows)}


def _lookup_device_type(ctx, slave_id: int, port: str | None) -> str | None:
    """Try to find device_type in config for (slave_id, port); return None if not found."""
    try:
        content = serial_conf.load_config(ctx)
        for dev in serial_conf.iter_devices(content):
            if dev.get("slave_id") == slave_id:
                if port is None or dev.get("port_path") == port:
                    return dev.get("device_type")
    except Exception:  # pylint: disable=broad-except
        pass
    return None


def _check_one(
    ctx,
    slave_id: int,
    port: dict,
    *,
    device_type: str | None = None,
    _swallow: bool = False,
) -> dict:
    """Probe one slave; on bulk failure (``_swallow``) attach the error instead of raising."""
    try:
        info = ctx.rpc.call(
            "wb-device-manager/fw-update/GetFirmwareInfo",
            {"slave_id": slave_id, "port": port},
            timeout=20.0,
        )
    except WbCliError as exc:
        if not _swallow:
            raise
        return {
            "slave_id": slave_id,
            "device_type": device_type or "",
            "port": port.get("path"),
            "error": exc.message,
        }
    if not isinstance(info, dict):
        info = {}
    return {
        "slave_id": slave_id,
        "device_type": device_type or "",
        "port": port.get("path"),
        "fw": info.get("fw"),
        "available_fw": info.get("available_fw"),
        "can_update": bool(info.get("can_update")),
        "bootloader": info.get("bootloader"),
        "available_bootloader": info.get("available_bootloader"),
    }


def _update(ctx) -> dict:
    if getattr(ctx.args, "background", False):
        return _update_background(ctx)

    if ctx.args.slave_id is not None:
        return _update_one(ctx, ctx.args.slave_id, _port_arg(ctx.args), ctx.args.software_type)

    if not ctx.args.all:
        raise WbCliError(
            code="MODBUS_FW_BULK_NEEDS_FLAG",
            message="Bulk update requires --all to acknowledge that every updatable device will be flashed",
            hint="Add --all, or pass a slave_id for a targeted update.",
            exit_code=ExitCode.USAGE,
        )
    content = serial_conf.load_config(ctx)
    targets = serial_conf.list_devices(content, port=ctx.args.port)
    queued, skipped = [], []
    for dev in targets:
        info = _check_one(ctx, dev["slave_id"], dev["port"], _swallow=True)
        if info.get("can_update"):
            queued.append(_update_one(ctx, dev["slave_id"], dev["port"], ctx.args.software_type))
        else:
            skipped.append({"slave_id": dev["slave_id"], "port": dev["port_path"]})
    return {
        "action": "update",
        "queued": queued,
        "skipped": skipped,
        "count": len(queued),
    }


def _update_background(ctx) -> dict:
    """Schedule the update via ``wb-cli job run`` and return the unit name."""
    args = ctx.args
    if not args.output:
        raise WbCliError(
            code="MODBUS_FW_OUTPUT_REQUIRED",
            message="--background requires --output PATH",
            hint=(
                "Write the long-flash JSON to a file under /mnt/data, "
                "e.g. --output /mnt/data/ai/wb-cli/wb-fw-$(date +%s).json"
            ),
            exit_code=ExitCode.USAGE,
        )
    parts = ["wb-cli", "--json", "serial", "wb-fw", "update"]
    if args.slave_id is not None:
        parts.append(str(args.slave_id))
    if args.port:
        parts += ["--port", shlex.quote(args.port)]
    if getattr(args, "all", False):
        parts.append("--all")
    if getattr(args, "software_type", "firmware") != "firmware":
        parts += ["--type", args.software_type]
    parts.append("--wait")  # the whole point of background is inside-the-job wait
    parts += [">", shlex.quote(args.output)]
    command = " ".join(parts)
    info = ctx.job.run("serial-wb-fw-update", command)
    return {
        "action": "update",
        "background": True,
        "output": args.output,
        "unit": info["unit"],
        "log": info["log"],
    }


def _update_one(ctx, slave_id: int, port: dict, software_type: str) -> dict:
    ctx.rpc.call(
        "wb-device-manager/fw-update/Update",
        {"slave_id": slave_id, "port": port, "type": software_type},
        timeout=15.0,
    )
    result = {
        "action": "update",
        "slave_id": slave_id,
        "port": port.get("path"),
        "type": software_type,
        "ok": True,
    }
    if getattr(ctx.args, "wait", False):
        result.update(_wait_for_completion(ctx, slave_id, port.get("path")))
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
        result.update(_wait_for_completion(ctx, args.slave_id, args.port))
    return result


def _wait_for_completion(ctx, slave_id: int, port: str) -> dict:
    """Block until the (slave_id, port) entry in the state topic finishes or errors."""
    deadline = time.monotonic() + 600.0
    with ctx.mqtt.live_sub(_STATE_TOPIC) as sub:
        with ProgressBar(f"flashing slave_id={slave_id}") as progress_bar:
            while time.monotonic() < deadline:
                for payload in sub.poll(0.1):
                    state = _parse_state(payload)
                    entry = _find_entry(state, slave_id, port)
                    if entry is None:
                        continue
                    progress_bar.update(entry.get("progress", 0), suffix=entry.get("type", ""))
                    if entry.get("error"):
                        return {"final": "error", "error": entry["error"]}
                    if entry.get("progress", 0) >= 100:
                        return {"final": "done"}
    return {"final": "timeout"}


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


def _render_check_one(result: dict) -> str:
    verdict = "update available" if result["can_update"] else "up to date"
    device_type = result.get("device_type") or ""
    header = f"{verdict}  (slave_id={result['slave_id']}, port={result['port']}"
    if device_type:
        header += f", {device_type}"
    header += ")"
    return "\n".join(
        [
            header,
            f"  firmware:   {result.get('fw', '?')} -> {result.get('available_fw', '?')}",
            f"  bootloader: {result.get('bootloader', '?')} -> " f"{result.get('available_bootloader', '?')}",
        ]
    )


def _render_check_bulk(rows) -> str:
    cols = [
        "slave_id",
        "device_type",
        "port",
        "fw",
        "available_fw",
        "bootloader",
        "available_bootloader",
        "status",
    ]
    has_error = any("error" in row for row in rows)
    if has_error:
        cols.append("error")
    table = []
    for row in rows:
        status = "ERROR" if "error" in row else ("update" if row.get("can_update") else "ok")
        entry = {
            "slave_id": str(row.get("slave_id", "?")),
            "device_type": row.get("device_type") or "",
            "port": row.get("port", "?"),
            "fw": str(row.get("fw") or ""),
            "available_fw": str(row.get("available_fw") or ""),
            "bootloader": str(row.get("bootloader") or ""),
            "available_bootloader": str(row.get("available_bootloader") or ""),
            "status": status,
        }
        if has_error:
            entry["error"] = (row.get("error") or "").splitlines()[0] if row.get("error") else ""
        table.append(entry)
    widths = {c: max(len(c), *(len(r[c]) for r in table)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    body = ["  ".join(r[c].ljust(widths[c]) for c in cols) for r in table]
    return "\n".join([f"checked {len(rows)} device(s):", header, sep, *body])


def _render_update_bulk(result: dict) -> str:
    queued = result.get("queued", [])
    skipped = result.get("skipped", [])
    lines = [f"queued {len(queued)} update(s), skipped {len(skipped)} (already current)"]
    for q in queued:
        lines.append(f"  + slave_id={q['slave_id']:<4} port={q['port']}")
    for s in skipped:
        lines.append(f"  . slave_id={s['slave_id']:<4} port={s['port']} (no update)")
    return "\n".join(lines)
