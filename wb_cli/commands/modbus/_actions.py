"""Modbus subcommand definitions and dispatch."""

from __future__ import annotations

import argparse
import json
import subprocess
import time

from wb_cli.errors import ExitCode, WbCliError


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


def _scan(ctx) -> dict:
    devices: list = []
    completed = False
    with subprocess.Popen(
        ["mosquitto_sub", "-t", "/wb-device-manager/state", "-F", "%p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ) as proc:
        try:
            ctx.rpc.call("wb-device-manager/bus-scan/Start", {})
            deadline = time.monotonic() + ctx.args.timeout
            while time.monotonic() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
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
                if state.get("progress", 0) >= 100:
                    devices = state.get("devices", [])
                    completed = True
                    break
        finally:
            try:
                ctx.rpc.call("wb-device-manager/bus-scan/Stop", {}, timeout=2.0)
            except WbCliError:
                pass
            proc.terminate()

    if not completed:
        raise WbCliError(
            code="MODBUS_SCAN_TIMEOUT",
            message=f"Bus scan did not finish within {ctx.args.timeout}s",
            details={"port": ctx.args.port, "timeout_seconds": ctx.args.timeout},
            exit_code=ExitCode.DOMAIN,
        )

    if ctx.args.port:
        devices = [d for d in devices if d.get("port", {}).get("path") == ctx.args.port]
    return {"port": ctx.args.port, "devices": devices, "count": len(devices)}


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
    return {
        "port": ctx.args.port,
        "address": ctx.args.address,
        "found": True,
        "result": result,
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
