"""Helpers around ``wb-mqtt-serial/port/Load`` (raw send) and port parameters.

Every plugin that talks Modbus at the raw-byte level (``serial send``,
``serial add-devices`` for baud / slave_id fixups, ``modbus-fw``) used to
inline its own ``port/Load`` parameter dict. Centralised here so the field
list is described once and the same UART defaults apply everywhere.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, Optional

# WB defaults: most WB devices ship at 9600/N/8/2. Override on the CLI when
# probing a different bus or a single device with non-default settings.
DEFAULT_BAUD_RATE = 9600
DEFAULT_PARITY = "N"
DEFAULT_DATA_BITS = 8
DEFAULT_STOP_BITS = 2

# wb-mqtt-serial expects total_timeout in ms; this matches the default the
# raw-send code paths used inline.
_DEFAULT_RESPONSE_TIMEOUT_MS = 500
_DEFAULT_FRAME_TIMEOUT_MS = 20
_DEFAULT_TOTAL_TIMEOUT_MS = 3000
# RPC timeout = total_timeout / 1000 + this many seconds of slack.
_RPC_TIMEOUT_SLACK_S = 5.0


def add_uart_args(
    parser: argparse.ArgumentParser,
    *,
    stop_bits_choices=None,
) -> None:
    """Add ``--baud / --parity / --data-bits / --stop-bits`` to ``parser``.

    Used by every CLI command that needs UART overrides (``serial send``,
    ``modbus-fw check``…). Default values come from the constants above.

    ``stop_bits_choices`` restricts the allowed values (``[1, 2]`` for
    ``serial send``; ``None`` means no restriction — useful for firmware
    update which sometimes needs 2 even if the device runs on 1).
    """
    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD_RATE,
        help=f"baud rate (default: {DEFAULT_BAUD_RATE})",
    )
    parser.add_argument(
        "--parity",
        default=DEFAULT_PARITY,
        choices=("N", "E", "O"),
        help=f"parity: N=none, E=even, O=odd (default: {DEFAULT_PARITY})",
    )
    parser.add_argument(
        "--data-bits",
        dest="data_bits",
        type=int,
        default=DEFAULT_DATA_BITS,
        help=f"data bits (default: {DEFAULT_DATA_BITS})",
    )
    stop_kwargs: Dict[str, Any] = {
        "dest": "stop_bits",
        "type": int,
        "default": DEFAULT_STOP_BITS,
        "help": f"stop bits (default: {DEFAULT_STOP_BITS})",
    }
    if stop_bits_choices is not None:
        stop_kwargs["choices"] = stop_bits_choices
    parser.add_argument("--stop-bits", **stop_kwargs)


def port_params(  # pylint: disable=too-many-arguments
    path: str,
    *,
    baud_rate: int = DEFAULT_BAUD_RATE,
    parity: str = DEFAULT_PARITY,
    data_bits: int = DEFAULT_DATA_BITS,
    stop_bits: int = DEFAULT_STOP_BITS,
) -> Dict[str, Any]:
    """Build the ``{path, baud_rate, parity, data_bits, stop_bits}`` dict.

    The exact shape ``wb-device-manager/bus-scan/Start`` and
    ``wb-mqtt-serial/port/Load`` expect for the ``port`` field.
    """
    return {
        "path": path,
        "baud_rate": baud_rate,
        "parity": parity,
        "data_bits": data_bits,
        "stop_bits": stop_bits,
    }


def port_params_from_args(args) -> Dict[str, Any]:
    """Build a port dict from a CLI Namespace populated by :func:`add_uart_args`.

    Picks up ``args.port``, ``args.baud``, ``args.parity``, ``args.data_bits``,
    ``args.stop_bits``. Centralised so every CLI command using these flags
    builds the dict the same way.
    """
    return port_params(
        args.port,
        baud_rate=args.baud,
        parity=args.parity,
        data_bits=args.data_bits,
        stop_bits=args.stop_bits,
    )


def port_params_from_cfg(path: str, cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build port params from a (possibly partial) UART config dict.

    Missing keys fall back to the WB defaults. Mirrors how ``wb-mqtt-serial``
    inherits port-level defaults onto devices.
    """
    cfg = cfg or {}
    return port_params(
        path,
        baud_rate=cfg.get("baud_rate", DEFAULT_BAUD_RATE),
        parity=cfg.get("parity", DEFAULT_PARITY),
        data_bits=cfg.get("data_bits", DEFAULT_DATA_BITS),
        stop_bits=cfg.get("stop_bits", DEFAULT_STOP_BITS),
    )


def raw_send(  # pylint: disable=too-many-arguments
    rpc,
    port: Dict[str, Any],
    *,
    msg: bytes,
    response_size: int,
    response_timeout_ms: int = _DEFAULT_RESPONSE_TIMEOUT_MS,
    frame_timeout_ms: int = _DEFAULT_FRAME_TIMEOUT_MS,
    total_timeout_ms: int = _DEFAULT_TOTAL_TIMEOUT_MS,
) -> Dict[str, Any]:
    """Send raw bytes via ``wb-mqtt-serial/port/Load`` and return the reply.

    ``port`` is the dict built by :func:`port_params` /
    :func:`port_params_from_cfg`. ``msg`` is the bytes to send (CRC already
    included if the protocol needs one). The RPC timeout is derived from
    ``total_timeout_ms`` with a few seconds of slack.

    Raises whatever ``rpc.call`` raises (``WbCliError`` with subsystem code).
    """
    params = {
        **port,
        "protocol": "raw",
        "format": "HEX",
        "msg": msg.hex(),
        "response_size": response_size,
        "response_timeout": response_timeout_ms,
        "frame_timeout": frame_timeout_ms,
        "total_timeout": total_timeout_ms,
    }
    rpc_timeout = total_timeout_ms / 1000.0 + _RPC_TIMEOUT_SLACK_S
    return rpc.call("wb-mqtt-serial/port/Load", params, timeout=rpc_timeout)
