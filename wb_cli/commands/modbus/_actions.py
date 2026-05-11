"""Modbus subcommand definitions and dispatch."""

from __future__ import annotations

import argparse
import json
import subprocess
import time

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.progress import ProgressBar

_BROKER_SETTLE_S = 1.0
_SUB_CONNECT_S = 0.5
_SCAN_STOP_TIMEOUT_S = 2.0


def register_all(sub: argparse._SubParsersAction) -> None:  # pylint: disable=too-many-statements
    """Register all modbus subcommand parsers."""
    _common = [
        ("-q", {"action": "store_true", "dest": "quiet"}),
    ]

    p = sub.add_parser("scan", help="scan RS-485 bus for devices")
    p.add_argument(
        "--port",
        default=None,
        help="filter results to this serial port path; scan still runs over all ports",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="seconds to wait for bus-scan completion (default: 60)",
    )
    for flag, kw in _common:
        p.add_argument(flag, **kw)

    p = sub.add_parser(
        "probe",
        help="probe a single Modbus address (assumes 9600-N-8-2)",
        description="Probe one slave address. Uses bus defaults: 9600 baud, N parity, 8 data, 2 stop.",
    )
    p.add_argument("--port", required=True, help="serial port path")
    p.add_argument("--address", type=int, required=True, help="slave address (1-247)")
    for flag, kw in _common:
        p.add_argument(flag, **kw)

    p = sub.add_parser("templates", help="list available device templates")
    for flag, kw in _common:
        p.add_argument(flag, **kw)

    p = sub.add_parser("template", help="show details of one template")
    p.add_argument(
        "template_id",
        help="template file name (with or without .json), e.g. config-wb-mr3",
    )
    for flag, kw in _common:
        p.add_argument(flag, **kw)

    p = sub.add_parser("device-info", help="show info about a configured device")
    p.add_argument("device_id", help="device slave_id or id in serial config")
    for flag, kw in _common:
        p.add_argument(flag, **kw)

    p = sub.add_parser("ports", help="list configured serial ports")
    for flag, kw in _common:
        p.add_argument(flag, **kw)

    p = sub.add_parser("add-devices", help="add scanned devices to config")
    p.add_argument("--port", required=True, help="serial port path")
    p.add_argument("--scan-results", required=True, help="JSON scan results")
    for flag, kw in _common:
        p.add_argument(flag, **kw)


def dispatch(ctx) -> dict:  # pylint: disable=too-many-return-statements
    subcmd = ctx.args.subcmd
    if subcmd == "scan":
        return _scan(ctx)
    if subcmd == "probe":
        return _probe(ctx)
    if subcmd == "templates":
        return _templates(ctx)
    if subcmd == "template":
        return _template(ctx)
    if subcmd == "device-info":
        return _device_info(ctx)
    if subcmd == "ports":
        return _ports(ctx)
    if subcmd == "add-devices":
        return _add_devices(ctx)
    return {}


def _open_state_stream():
    """Subscribe to /wb-device-manager/state via mosquitto_sub, drop retained."""
    try:
        return subprocess.Popen(
            ["mosquitto_sub", "-R", "-t", "/wb-device-manager/state", "-F", "%p"],
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


def _await_regular_scan(ctx, proc, progress_bar):
    """Block until the *regular* (non-extended) bus scan reports progress=100."""
    deadline = time.monotonic() + ctx.args.timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            state = json.loads(line)
        except json.JSONDecodeError:
            continue
        if state.get("error"):
            raise WbCliError(
                code="MODBUS_SCAN_FAILED",
                message=f"Bus scan reported error: {state['error']}",
                details={"port": ctx.args.port, "state": state},
                exit_code=ExitCode.DOMAIN,
            )
        progress = state.get("progress", 0)
        is_ext = state.get("is_ext_scan", False)
        dev_count = len(state.get("devices", []))
        phase = "extended" if is_ext else "regular"
        progress_bar.update(progress, suffix=f"{phase}, {dev_count} device(s)")
        if progress >= 100 and not is_ext:
            return state.get("devices", [])
    return None


def _scan(ctx) -> dict:
    # Cancel any previous scan and let the broker quiesce so we don't pick
    # up its tail state messages.
    try:
        ctx.rpc.call("wb-device-manager/bus-scan/Stop", {}, timeout=_SCAN_STOP_TIMEOUT_S)
    except WbCliError:
        pass
    time.sleep(_BROKER_SETTLE_S)

    spinner_label = f"scanning {ctx.args.port}" if ctx.args.port else "scanning RS-485 bus"
    proc = _open_state_stream()
    devices: list = []
    # wb-device-manager replays the previous extended scan first, then runs
    # the regular bus scan.  Wait for the regular scan to reach progress=100.
    with proc, ProgressBar(spinner_label) as progress_bar:
        try:
            time.sleep(_SUB_CONNECT_S)
            ctx.rpc.call("wb-device-manager/bus-scan/Start", {})
            result = _await_regular_scan(ctx, proc, progress_bar)
            if result is not None:
                devices = result
        finally:
            try:
                ctx.rpc.call("wb-device-manager/bus-scan/Stop", {}, timeout=_SCAN_STOP_TIMEOUT_S)
            except WbCliError:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()

    if result is None:
        raise WbCliError(
            code="MODBUS_SCAN_TIMEOUT",
            message=f"Bus scan did not finish within {ctx.args.timeout}s",
            details={"port": ctx.args.port, "timeout_seconds": ctx.args.timeout},
            exit_code=ExitCode.DOMAIN,
        )

    if ctx.args.port:
        devices = [d for d in devices if d.get("port", {}).get("path") == ctx.args.port]
    result: dict = {"devices": devices, "count": len(devices)}
    if ctx.args.port:
        result["port"] = ctx.args.port
    return result


def _probe(ctx) -> dict:
    params = {
        "path": ctx.args.port,
        "baud_rate": 9600,
        "parity": "N",
        "data_bits": 8,
        "stop_bits": 2,
        "slave_id": ctx.args.address,
    }
    try:
        result = ctx.rpc.call("wb-mqtt-serial/device/Probe", params)
    except WbCliError as exc:
        return {
            "port": ctx.args.port,
            "address": ctx.args.address,
            "found": False,
            "error": exc.message,
        }
    # device/Probe returns `{}` when nothing answers on that address —
    # treat an empty result as "no device", not a successful probe.
    found = bool(result) and bool(result.get("device_signature") or result.get("sn"))
    return {
        "port": ctx.args.port,
        "address": ctx.args.address,
        "found": found,
        "result": result if found else None,
    }


def _templates(ctx) -> dict:
    _, stdout, _ = ctx.shell.run(
        ["find", "/usr/share/wb-mqtt-serial/templates", "-name", "*.json", "-printf", "%f\n"],
        timeout=5.0,
    )
    names = sorted(stdout.strip().splitlines()) if stdout.strip() else []
    return {"templates": names, "count": len(names)}


def _template(ctx) -> dict:
    template_id = ctx.args.template_id
    filename = template_id if template_id.endswith(".json") else f"{template_id}.json"
    rc, stdout, _ = ctx.shell.run(
        ["cat", f"/usr/share/wb-mqtt-serial/templates/{filename}"],
        timeout=5.0,
    )
    if rc != 0:
        raise WbCliError(
            code="MODBUS_TEMPLATE_NOT_FOUND",
            message=f"Template '{template_id}' not found",
            details={"template_id": template_id, "filename": filename},
            exit_code=ExitCode.DOMAIN,
        )
    try:
        template = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise WbCliError(
            code="MODBUS_TEMPLATE_INVALID",
            message=f"Template '{template_id}' is not valid JSON: {exc}",
            details={"template_id": template_id},
            exit_code=ExitCode.DOMAIN,
        ) from exc
    return {"template_id": template_id, "template": template}


def _device_info(ctx) -> dict:
    result = ctx.rpc.call("confed/Editor/Load", {"path": "/etc/wb-mqtt-serial.conf"})
    content = result.get("content", result) if isinstance(result, dict) else {}
    devices = []
    for port in content.get("ports", []) if isinstance(content, dict) else []:
        devices.extend(port.get("devices", []))
    for dev in devices:
        if str(dev.get("slave_id")) == str(ctx.args.device_id) or dev.get("id") == ctx.args.device_id:
            return {"device": dev}
    raise WbCliError(
        code="DEVICES_DEVICE_NOT_FOUND",
        message=f"Device '{ctx.args.device_id}' not in serial config",
        details={"device_id": ctx.args.device_id},
        exit_code=ExitCode.DOMAIN,
    )


def _ports(ctx) -> dict:
    result = ctx.rpc.call("wb-mqtt-serial/ports/Load", {})
    ports = result if isinstance(result, list) else result.get("ports", [])
    return {"ports": ports, "count": len(ports)}


def _add_devices(ctx) -> dict:
    try:
        scan_results = json.loads(ctx.args.scan_results)
    except json.JSONDecodeError as exc:
        raise WbCliError(
            code="MODBUS_ADD_NO_DEVICES",
            message=f"--scan-results is not valid JSON: {exc}",
            exit_code=ExitCode.DOMAIN,
        ) from exc

    if not scan_results:
        raise WbCliError(
            code="MODBUS_ADD_NO_DEVICES",
            message="No devices in scan results to add",
            exit_code=ExitCode.DOMAIN,
        )

    result = ctx.rpc.call("confed/Editor/Load", {"path": "/etc/wb-mqtt-serial.conf"})
    content = result.get("content", {}) if isinstance(result, dict) else {}
    ports = content.get("ports", []) if isinstance(content, dict) else []
    target_port = None
    for port in ports:
        if port.get("path") == ctx.args.port:
            target_port = port
            break
    if target_port is None:
        raise WbCliError(
            code="MODBUS_ADD_NO_DEVICES",
            message=f"Port '{ctx.args.port}' not found in serial config",
            details={"port": ctx.args.port},
            exit_code=ExitCode.DOMAIN,
        )
    added = []
    for dev in scan_results:
        target_port.setdefault("devices", []).append(dev)
        added.append(dev.get("id", dev.get("slave_id", "unknown")))

    ctx.rpc.call(
        "confed/Editor/Save",
        {"path": "/etc/wb-mqtt-serial.conf", "content": content},
    )
    return {"port": ctx.args.port, "added": added, "count": len(added)}
