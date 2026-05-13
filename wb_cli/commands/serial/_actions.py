"""``wb-cli serial`` dispatch + small actions.

Heavy flows live in sibling modules:

  * ``_register.py`` — argparse parsers (``register_all``)
  * ``_scan.py``     — bus-scan flow
  * ``_add.py``      — add-devices flow (incl. bus-side fixups)

This file keeps the dispatcher and the actions short enough to fit in one
glance: ``send``, ``device-info``, ``device-params``, ``device-set``,
``devices``, ``ports``, ``templates``, ``template``.
"""

from __future__ import annotations

import json

from wb_cli.commands.serial._add import (
    add_devices as _add_devices_impl,  # re-exported for back-compat in tests
)
from wb_cli.commands.serial._add import find_free_slave_id as _find_free_slave_id
from wb_cli.commands.serial._add import (
    required_params_from_template as _required_params_from_template,
)
from wb_cli.commands.serial._register import register_all  # re-export
from wb_cli.commands.serial._scan import scan as _scan_impl
from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib import serial_conf, serial_port, templates
from wb_cli.lib.modbus_crc import modbus_crc16

__all__ = [
    "register_all",
    "dispatch",
    "_fmt_hex",  # used by _plugin.py for human-mode rendering
    "_parse_hex_msg",  # used in tests
    "_find_free_slave_id",  # used in tests
    "_parse_param_assignments",  # used in tests
    "_required_params_from_template",  # used in tests
]


def dispatch(ctx) -> dict:  # pylint: disable=too-many-return-statements
    subcmd = ctx.args.subcmd
    if subcmd == "send":
        return _send(ctx)
    if subcmd == "wb-scan":
        return _scan_impl(ctx)
    if subcmd == "templates":
        return _templates()
    if subcmd == "template":
        return _template(ctx)
    if subcmd == "device-info":
        return _device_info(ctx)
    if subcmd == "device-params":
        return _device_params(ctx)
    if subcmd == "device-set":
        return _device_set(ctx)
    if subcmd == "devices":
        return _devices(ctx)
    if subcmd == "ports":
        return _ports(ctx)
    if subcmd == "add-devices":
        return _add_devices_impl(ctx)
    return {}


# --------------------------------------------------------------------------- #
# helpers — hex parsing & formatting
# --------------------------------------------------------------------------- #


def _parse_hex_msg(raw: str) -> bytes:
    """Strip spaces and 0x-prefixes, parse as hex bytes."""
    cleaned = raw.replace(" ", "").replace("0x", "").replace("0X", "")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"invalid hex message {raw!r}: {exc}") from exc


def _fmt_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


# --------------------------------------------------------------------------- #
# send / device-params / device-set
# --------------------------------------------------------------------------- #


def _send(ctx) -> dict:
    args = ctx.args
    msg = _parse_hex_msg(args.msg)
    if args.add_modbus_crc:
        msg += modbus_crc16(msg)
    port = serial_port.port_params_from_args(args)
    result = serial_port.raw_send(
        ctx.rpc,
        port,
        msg=msg,
        response_size=args.response_size,
        response_timeout_ms=args.response_timeout,
        frame_timeout_ms=args.frame_timeout,
        total_timeout_ms=args.total_timeout,
    )
    return {"port": args.port, "request": msg.hex(), "response": result.get("response", "").lower()}


def _resolve_device_from_config(ctx) -> dict:
    content = serial_conf.load_config(ctx)
    for dev in serial_conf.iter_devices(content):
        if str(dev.get("slave_id")) == str(ctx.args.device_id) or dev.get("id") == ctx.args.device_id:
            return dev
    raise WbCliError(
        code="SERIAL_DEVICE_NOT_FOUND",
        message=f"Device '{ctx.args.device_id}' not in {serial_conf.CONFIG_PATH}",
        details={"device_id": ctx.args.device_id},
        exit_code=ExitCode.DOMAIN,
    )


def _build_device_rpc_params(dev: dict) -> dict:
    port = dev["port"]
    return {
        "path": port["path"],
        "baud_rate": port["baud_rate"],
        "parity": port.get("parity", serial_port.DEFAULT_PARITY),
        "data_bits": port.get("data_bits", serial_port.DEFAULT_DATA_BITS),
        "stop_bits": port.get("stop_bits", serial_port.DEFAULT_STOP_BITS),
        "slave_id": dev["slave_id"],
        "device_type": dev["device_type"],
    }


def _device_params(ctx) -> dict:
    dev = _resolve_device_from_config(ctx)
    params = _build_device_rpc_params(dev)
    if getattr(ctx.args, "force", False):
        params["force"] = True
    result = ctx.rpc.call("wb-mqtt-serial/device/LoadConfig", params, timeout=30.0)
    return {"slave_id": dev["slave_id"], "device_type": dev["device_type"], **result}


def _parse_param_assignments(args) -> dict:
    """Parse ``--set KEY=VALUE`` pairs; coerce values to int → float → str."""
    result = {}
    for kv in args.params or []:
        if "=" not in kv:
            raise WbCliError(
                code="SERIAL_INVALID_PARAM",
                message=f"invalid --set value {kv!r}: expected KEY=VALUE",
                exit_code=ExitCode.USAGE,
            )
        key, value = kv.split("=", 1)
        try:
            result[key] = int(value)
        except ValueError:
            try:
                result[key] = float(value)
            except ValueError:
                result[key] = value
    return result


def _device_set(ctx) -> dict:
    dev = _resolve_device_from_config(ctx)
    params = _build_device_rpc_params(dev)
    params["parameters"] = _parse_param_assignments(ctx.args)
    ctx.rpc.call("wb-mqtt-serial/device/Set", params, timeout=30.0)
    return {"slave_id": dev["slave_id"], "device_type": dev["device_type"], "set": params["parameters"]}


# --------------------------------------------------------------------------- #
# templates / template / device-info / devices / ports
# --------------------------------------------------------------------------- #


def _templates() -> dict:
    names = templates.list_template_names()
    return {"templates": names, "count": len(names)}


def _template(ctx) -> dict:
    template_id = ctx.args.template_id
    try:
        template = templates.read_template(template_id)
    except json.JSONDecodeError as exc:
        raise WbCliError(
            code="MODBUS_TEMPLATE_INVALID",
            message=f"Template '{template_id}' is not valid JSON: {exc}",
            details={"template_id": template_id},
            exit_code=ExitCode.DOMAIN,
        ) from exc
    if template is None:
        raise WbCliError(
            code="MODBUS_TEMPLATE_NOT_FOUND",
            message=f"Template '{template_id}' not found",
            details={"template_id": template_id},
            exit_code=ExitCode.DOMAIN,
        )
    return {"template_id": template_id, "template": template}


def _device_info(ctx) -> dict:
    content = serial_conf.load_config(ctx)
    for dev in serial_conf.iter_devices(content):
        if str(dev["slave_id"]) == str(ctx.args.device_id) or dev["id"] == ctx.args.device_id:
            return {"device": dev}
    raise WbCliError(
        code="MODBUS_DEVICE_NOT_FOUND",
        message=f"Device '{ctx.args.device_id}' not in {serial_conf.CONFIG_PATH}",
        details={"device_id": ctx.args.device_id},
        exit_code=ExitCode.DOMAIN,
    )


def _devices(ctx) -> dict:
    content = serial_conf.load_config(ctx)
    devices = serial_conf.list_devices(content, port=ctx.args.port)
    return {"devices": devices, "count": len(devices)}


def _ports(ctx) -> dict:
    """List active serial ports as wb-mqtt-serial sees them.

    Empty result == driver dropped the port (usually a schema validation
    failure). The fix is to repair the config, not to bypass the RPC.
    """
    result = ctx.rpc.call("wb-mqtt-serial/ports/Load", {})
    ports = result if isinstance(result, list) else result.get("ports", [])
    return {"ports": ports, "count": len(ports)}
