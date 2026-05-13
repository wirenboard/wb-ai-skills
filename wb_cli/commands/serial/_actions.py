"""``wb-cli serial`` dispatch + small actions.

Heavy flows live in sibling modules:

  * ``_register.py`` — argparse parsers (``register_all``)
  * ``_scan.py``     — bus-scan flow
  * ``_add.py``      — add-devices flow (incl. bus-side fixups)
  * ``_wb_fw.py``    — firmware update (folded in from ``modbus-fw`` in 1.8.0)

This file keeps the dispatcher and the actions short enough to fit in one
glance: ``send``, ``send-modbus``, ``config``, ``fw-params``, ``ports``,
``templates``, ``template``, ``wb-set-slave-id``, ``wb-set-baud``.
"""

from __future__ import annotations

import json
import struct

from wb_cli.commands.serial import _wb_fw
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
from wb_cli.lib import serial_bus, serial_conf, serial_port, templates
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


def dispatch(ctx) -> dict:  # pylint: disable=too-many-return-statements,too-many-branches
    subcmd = ctx.args.subcmd
    if subcmd == "send":
        return _send(ctx)
    if subcmd == "send-modbus":
        return _send_modbus(ctx)
    if subcmd == "wb-scan":
        return _scan_impl(ctx)
    if subcmd == "templates":
        return _templates()
    if subcmd == "template":
        return _template(ctx)
    if subcmd == "config":
        return _config(ctx)
    if subcmd == "fw-params":
        return _fw_params(ctx)
    if subcmd == "ports":
        return _ports(ctx)
    if subcmd == "add-devices":
        return _add_devices_impl(ctx)
    if subcmd == "wb-set-slave-id":
        return _wb_set_slave_id(ctx)
    if subcmd == "wb-set-baud":
        return _wb_set_baud(ctx)
    if subcmd == "wb-fw":
        return _wb_fw.dispatch(ctx)
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
    try:
        msg = _parse_hex_msg(args.msg)
    except ValueError as exc:
        raise WbCliError(
            code="SERIAL_INVALID_HEX",
            message=str(exc),
            hint='Use a hex string like "FD 46 01" or "fd4601" — spaces and 0x-prefix are optional.',
            details={"msg": args.msg},
            exit_code=ExitCode.USAGE,
        ) from exc
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


def _fw_params(ctx) -> dict:
    """``serial fw-params`` — read or write firmware parameters of one device.

    Positional ``params`` (list of ``key=value`` strings) chooses read vs write:
      * empty → read (RPC ``wb-mqtt-serial/device/LoadConfig``).
        ``--force`` bypasses the driver's cache.
      * non-empty → write. Default path goes through the config (confed Load,
        patch, Save → driver reload → applied to hardware): persistent across
        restarts. ``--force`` skips the config and writes through the driver
        directly (``wb-mqtt-serial/device/Set``) — one-shot, reverts on next
        driver restart.
    """
    if ctx.args.params:
        return _fw_params_write(ctx)
    return _fw_params_read(ctx)


def _fw_params_read(ctx) -> dict:
    dev = _resolve_device_from_config(ctx)
    params = _build_device_rpc_params(dev)
    if getattr(ctx.args, "force", False):
        params["force"] = True
    result = ctx.rpc.call("wb-mqtt-serial/device/LoadConfig", params, timeout=30.0)
    return {"slave_id": dev["slave_id"], "device_type": dev["device_type"], **result}


def _parse_param_assignments(raw_pairs) -> dict:
    """Parse positional ``KEY=VALUE`` pairs; coerce values to int → float → str."""
    result = {}
    for kv in raw_pairs or []:
        if "=" not in kv:
            raise WbCliError(
                code="SERIAL_INVALID_PARAM",
                message=f"invalid param {kv!r}: expected KEY=VALUE",
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


def _fw_params_write(ctx) -> dict:
    """Write firmware parameters — default through config, ``--force`` direct to device."""
    dev = _resolve_device_from_config(ctx)
    new_params = _parse_param_assignments(ctx.args.params)
    if getattr(ctx.args, "force", False):
        return _fw_params_write_direct(ctx, dev, new_params)
    return _fw_params_write_via_config(ctx, dev, new_params)


def _fw_params_write_direct(ctx, dev: dict, new_params: dict) -> dict:
    """Write through ``wb-mqtt-serial/device/Set`` RPC, bypassing the config.

    One-shot: the driver re-applies the config on next restart, which will
    overwrite these values with whatever is in ``/etc/wb-mqtt-serial.conf``.
    """
    rpc_params = _build_device_rpc_params(dev)
    rpc_params["parameters"] = new_params
    ctx.rpc.call("wb-mqtt-serial/device/Set", rpc_params, timeout=30.0)
    return {
        "slave_id": dev["slave_id"],
        "device_type": dev["device_type"],
        "set": new_params,
        "via": "device",
    }


def _fw_params_write_via_config(ctx, dev: dict, new_params: dict) -> dict:
    """Patch the device entry in /etc/wb-mqtt-serial.conf and confed Save.

    confed validates against the schema, persists the file, and reloads
    wb-mqtt-serial — which then re-applies the parameters to the device.
    Persistent across driver restarts.
    """
    result = ctx.rpc.call("confed/Editor/Load", {"path": serial_conf.CONFIG_PATH})
    content = result.get("content", result) if isinstance(result, dict) else result
    target = _find_device_entry_in_content(content, ctx.args.device_id)
    if target is None:
        raise WbCliError(
            code="SERIAL_DEVICE_NOT_FOUND",
            message=f"Device '{ctx.args.device_id}' not in {serial_conf.CONFIG_PATH}",
            details={"device_id": ctx.args.device_id},
            exit_code=ExitCode.DOMAIN,
        )
    for key, value in new_params.items():
        target[key] = value
    ctx.rpc.call(
        "confed/Editor/Save",
        {"path": serial_conf.CONFIG_PATH, "content": content},
    )
    return {
        "slave_id": dev["slave_id"],
        "device_type": dev["device_type"],
        "set": new_params,
        "via": "config",
    }


def _find_device_entry_in_content(content: dict, device_id) -> dict | None:
    """Return the mutable device-dict from the raw confed content (not the
    inherited copy from ``serial_conf.iter_devices``) so we can patch it
    in place and save."""
    if not isinstance(content, dict):
        return None
    for port in content.get("ports", []) or []:
        for dev in port.get("devices", []) or []:
            if str(dev.get("slave_id")) == str(device_id) or dev.get("id") == device_id:
                return dev
    return None


# --------------------------------------------------------------------------- #
# templates / template / config / ports
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


def _config(ctx) -> dict:
    """``serial config [<id>] [--port <path>]`` — read /etc/wb-mqtt-serial.conf.

    Without an id, returns the compact device list (optionally filtered by
    port) — the same UART-resolved view ``iter_devices`` builds.

    With an id, returns the **raw** device dict from the config file —
    every key the user (or web UI / add-devices) wrote there, including
    template parameters like ``disable_indication`` that ``iter_devices``
    doesn't expose. Looks up by numeric slave_id or by the string ``id``
    field some templates set.
    """
    content = serial_conf.load_config(ctx)
    device_id = getattr(ctx.args, "device_id", None)
    if device_id is None:
        devices = serial_conf.list_devices(content, port=ctx.args.port)
        return {"devices": devices, "count": len(devices)}
    raw = _find_device_entry_in_content(content, device_id)
    if raw is None:
        raise WbCliError(
            code="MODBUS_DEVICE_NOT_FOUND",
            message=f"Device '{device_id}' not in {serial_conf.CONFIG_PATH}",
            details={"device_id": device_id},
            exit_code=ExitCode.DOMAIN,
        )
    return {"device": raw}


def _ports(ctx) -> dict:
    """List active serial ports as wb-mqtt-serial sees them.

    Empty result == driver dropped the port (usually a schema validation
    failure). The fix is to repair the config, not to bypass the RPC.
    """
    result = ctx.rpc.call("wb-mqtt-serial/ports/Load", {})
    ports = result if isinstance(result, list) else result.get("ports", [])
    return {"ports": ports, "count": len(ports)}


# --------------------------------------------------------------------------- #
# send-modbus / wb-set-slave-id / wb-set-baud
# --------------------------------------------------------------------------- #


def _send_modbus(ctx) -> dict:
    """Send a Modbus PDU built from structured args; parse the response."""
    args = ctx.args
    port = serial_port.port_params_from_args(args)
    if args.fc in (3, 4):
        pdu = struct.pack(">BBHH", args.slave, args.fc, args.reg, args.count)
        frame = pdu + modbus_crc16(pdu)
        expected = 5 + 2 * args.count  # slave + fc + bytecount + 2*N + crc(2)
    elif args.fc == 6:
        if args.value is None:
            raise WbCliError(
                code="SERIAL_FC6_NEEDS_VALUE",
                message="FC6 (write single register) requires --value",
                hint="Add `--value N`.",
                exit_code=ExitCode.USAGE,
            )
        from wb_cli.lib import (  # local import: avoid cycle  pylint: disable=import-outside-toplevel
            modbus_frame,
        )

        frame = modbus_frame.fc6_write(args.slave, args.reg, args.value)
        expected = 8
    else:  # pragma: no cover — choices=[3,4,6] in argparse keeps us out of here
        raise WbCliError(
            code="SERIAL_UNSUPPORTED_FC",
            message=f"function code {args.fc} not supported by send-modbus",
            hint="Use `serial send` with a hand-built PDU for other FCs.",
            exit_code=ExitCode.USAGE,
        )
    result = serial_port.raw_send(
        ctx.rpc,
        port,
        msg=frame,
        response_size=expected,
        response_timeout_ms=args.response_timeout,
        frame_timeout_ms=args.frame_timeout,
        total_timeout_ms=args.total_timeout,
    )
    resp_hex = (result.get("response") or "").lower()
    out = {
        "port": args.port,
        "slave_id": args.slave,
        "fc": args.fc,
        "reg": args.reg,
        "request": frame.hex(),
        "response": resp_hex,
    }
    if args.fc in (3, 4):
        out["count"] = args.count
        out["registers"] = _parse_modbus_register_response(resp_hex, args.count)
    else:
        out["value"] = args.value
    return out


def _parse_modbus_register_response(resp_hex: str, count: int) -> list[int]:
    """Decode the data portion of a Modbus FC3/FC4 response into a list of ints.

    Returns ``[]`` on any malformed / short payload so the caller still gets
    the raw hex and can decide how to handle the error.
    """
    if not resp_hex:
        return []
    try:
        data = bytes.fromhex(resp_hex)
    except ValueError:
        return []
    if len(data) < 3 + 2 * count + 2:
        return []
    body = data[3 : 3 + 2 * count]
    return list(struct.unpack(f">{count}H", body))


def _wb_set_slave_id(ctx) -> dict:
    """Change a WB device's slave_id via FC6 reg 128 (standard or Fast Modbus by SN)."""
    args = ctx.args
    port = serial_port.port_params_from_args(args)
    if args.sn is not None:
        sn = _parse_hex_int(args.sn, "--sn")
        serial_bus.change_slave_id_by_sn(ctx.rpc, port, sn, args.new_id)
        via = "fast-modbus-by-sn"
    else:
        serial_bus.change_slave_id_standard(ctx.rpc, port, args.current_id, args.new_id)
        via = "standard-fc6-reg128"
    return {
        "action": "wb-set-slave-id",
        "port": args.port,
        "current_id": args.current_id,
        "new_id": args.new_id,
        "sn": args.sn,
        "via": via,
        "ok": True,
    }


def _wb_set_baud(ctx) -> dict:
    """Change a WB device's baud rate via FC6 reg 110."""
    args = ctx.args
    if args.new_baud % 100 != 0 or args.new_baud <= 0:
        raise WbCliError(
            code="SERIAL_INVALID_BAUD",
            message=f"baud rate {args.new_baud!r} must be a positive multiple of 100",
            hint="Typical values: 9600, 19200, 38400, 57600, 115200.",
            exit_code=ExitCode.USAGE,
        )
    port = serial_port.port_params_from_args(args)
    serial_bus.change_baud(ctx.rpc, port, args.slave_id, args.new_baud)
    return {
        "action": "wb-set-baud",
        "port": args.port,
        "slave_id": args.slave_id,
        "old_baud": args.baud,
        "new_baud": args.new_baud,
        "ok": True,
    }


def _parse_hex_int(raw: str, label: str) -> int:
    try:
        return int(raw, 0)
    except (TypeError, ValueError) as exc:
        raise WbCliError(
            code="SERIAL_INVALID_HEX",
            message=f"invalid {label} value {raw!r}: {exc}",
            hint="Pass a decimal or 0x-prefixed hex int (e.g. 0x00020B86 or 134022).",
            exit_code=ExitCode.USAGE,
        ) from exc
