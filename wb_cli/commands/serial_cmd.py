"""``wb-cli serial`` — serial port operations: send raw bytes, etc."""

from __future__ import annotations

import argparse
import struct

from wb_cli.plugin import BasePlugin


def _modbus_crc16(data: bytes) -> bytes:
    """Standard Modbus CRC-16, little-endian (appended as 2 bytes)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack("<H", crc)


def _parse_hex_msg(raw: str) -> bytes:
    """Strip spaces and 0x-prefixes, parse as hex bytes."""
    cleaned = raw.replace(" ", "").replace("0x", "").replace("0X", "")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"invalid hex message {raw!r}: {exc}") from exc


def _fmt_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


class SerialPlugin(BasePlugin):
    name = "serial"
    help = "serial port operations: send raw bytes to the bus via wb-mqtt-serial RPC"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Serial port operations — send raw frames, inspect responses.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser(
            "send",
            help="send raw bytes to the serial bus and read the response",
            description=(
                "Sends arbitrary bytes to a serial port through wb-mqtt-serial's port/Load\n"
                "RPC and returns the response. The driver keeps running — the request is\n"
                "queued alongside regular polling. No restart needed.\n"
                "\n"
                "Useful for Fast Modbus frames (address changes, scan), non-Modbus\n"
                "protocols, and low-level debugging without stopping the serial driver.\n"
                "\n"
                "Message format: hex string, spaces and 0x-prefixes are stripped.\n"
                "Use --add-modbus-crc to append a Modbus CRC-16 automatically.\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=(
                "Examples:\n"
                "  # Fast Modbus scan start — ask all WB devices to identify themselves\n"
                "  wb-cli serial send --port /dev/ttyRS485-1 \\\n"
                "      --msg 'FD 46 01' --add-modbus-crc --response-size 10\n"
                "\n"
                "  # Change slave_id of device SN=0x00020B86 to 5 (Fast Modbus by SN)\n"
                "  wb-cli serial send --port /dev/ttyRS485-1 \\\n"
                "      --msg 'FD 46 08 00 02 0B 86 06 00 80 00 05' --add-modbus-crc --response-size 14\n"
                "\n"
                "  # Read holding registers 0-19 from slave_id=2 (standard Modbus FC3)\n"
                "  wb-cli serial send --port /dev/ttyRS485-1 \\\n"
                "      --msg '02 03 00 00 00 14' --add-modbus-crc --response-size 45\n"
                "\n"
                "  # Broadcast baud-rate change to 115200 for all WB devices (reg 110 = 1152)\n"
                "  wb-cli serial send --port /dev/ttyRS485-1 \\\n"
                "      --msg '00 06 00 6E 04 80' --add-modbus-crc\n"
            ),
        )
        p.add_argument("--port", required=True, help="serial port path (e.g. /dev/ttyRS485-1)")
        p.add_argument("--baud", type=int, default=9600, help="baud rate (default: 9600)")
        p.add_argument(
            "--parity",
            default="N",
            choices=["N", "E", "O"],
            help="parity: N=none, E=even, O=odd (default: N)",
        )
        p.add_argument(
            "--stop-bits",
            type=int,
            default=2,
            dest="stop_bits",
            choices=[1, 2],
            help="stop bits (default: 2)",
        )
        p.add_argument(
            "--msg",
            required=True,
            help="bytes to send as a hex string, spaces allowed (e.g. 'FD 46 01' or 'fd4601')",
        )
        p.add_argument(
            "--add-modbus-crc",
            action="store_true",
            dest="add_modbus_crc",
            help="append Modbus CRC-16 (little-endian) to the message before sending",
        )
        p.add_argument(
            "--response-size",
            type=int,
            default=0,
            dest="response_size",
            help="bytes to read back (0 = fire-and-forget; default: 0)",
        )
        p.add_argument(
            "--response-timeout",
            type=int,
            default=500,
            dest="response_timeout",
            help="ms to wait for the first response byte (default: 500)",
        )
        p.add_argument(
            "--frame-timeout",
            type=int,
            default=20,
            dest="frame_timeout",
            help="ms inter-byte gap that ends the frame (default: 20)",
        )
        p.add_argument(
            "--total-timeout",
            type=int,
            default=5000,
            dest="total_timeout",
            help="ms total timeout for the whole operation (default: 5000)",
        )

    def dispatch(self, ctx) -> dict:
        if ctx.args.subcmd == "send":
            return _send(ctx)
        return {}

    def render(self, result):
        if "request" not in result:
            return None
        req = _fmt_hex(bytes.fromhex(result["request"]))
        lines = [f"→ {req}"]
        resp_hex = result.get("response", "")
        if resp_hex:
            lines.append(f"← {_fmt_hex(bytes.fromhex(resp_hex))}")
        else:
            lines.append("(no response)")
        return "\n".join(lines)


def _send(ctx) -> dict:
    args = ctx.args
    msg = _parse_hex_msg(args.msg)
    if args.add_modbus_crc:
        msg += _modbus_crc16(msg)

    params = {
        "path": args.port,
        "baud_rate": args.baud,
        "parity": args.parity,
        "data_bits": 8,
        "stop_bits": args.stop_bits,
        "protocol": "raw",
        "format": "HEX",
        "msg": msg.hex(),
        "response_size": args.response_size,
        "response_timeout": args.response_timeout,
        "frame_timeout": args.frame_timeout,
        "total_timeout": args.total_timeout,
    }

    rpc_timeout = args.total_timeout / 1000 + 5
    result = ctx.rpc.call("wb-mqtt-serial/port/Load", params, timeout=rpc_timeout)
    response_hex = result.get("response", "")

    return {
        "port": args.port,
        "request": msg.hex(),
        "response": response_hex.lower(),
    }


PLUGIN = SerialPlugin()
