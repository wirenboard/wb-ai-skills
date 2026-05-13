"""argparse parser tree for ``wb-cli serial`` subcommands.

Only argparse boilerplate lives here; the actual dispatch and implementations
are in ``_actions.py`` (small actions) and ``_scan.py`` / ``_add.py``
(scan and add-devices flows).
"""

from __future__ import annotations

import argparse

from wb_cli.lib import serial_port


def register_all(sub: argparse._SubParsersAction) -> None:  # pylint: disable=too-many-statements
    """Register every ``wb-cli serial <action>`` parser onto ``sub``."""
    _register_wb_scan(sub)
    _register_templates(sub)
    _register_template(sub)
    _register_config(sub)
    _register_fw_params(sub)
    _register_ports(sub)
    _register_add_devices(sub)
    _register_send(sub)


def _register_wb_scan(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "wb-scan",
        help="Finds WB Fast Modbus devices (WB, Onokom and compatible)",
        description=(
            "Runs wb-device-manager's bus scan and returns what answered. Same flow\n"
            "the web UI's three scan buttons trigger.\n"
            "\n"
            "  (default)     web-UI «Поиск устройств». WB Fast Modbus — an extension\n"
            "                of standard Modbus, supported by current WB firmware.\n"
            "                Finds every device on the bus that speaks Fast Modbus\n"
            "                (typically all of them on a modern setup).\n"
            "  --slow        web-UI «Начать медленное сканирование». Classic Modbus\n"
            "                poll over every UART combo (8 baud × 3 parity × 2 stop).\n"
            "                Use when the default Fast Modbus pass misses devices —\n"
            "                older firmware without Fast Modbus, or non-default UART.\n"
            "                Takes minutes; raise --timeout accordingly.\n"
            "  --bootloader  web-UI «Поиск устройств в режиме загрузчика». Looks for\n"
            "                devices stuck after a failed `modbus-fw update`.\n"
            "\n"
            "All three modes pass `preserve_old_results=false` so we get a fresh\n"
            "result instead of the retained cache from the previous scan.\n"
            "--slow and --bootloader are mutually exclusive."
        ),
        epilog=(
            "Examples:\n"
            "  wb-cli serial wb-scan                                    # default — finds everything\n"
            "  wb-cli serial wb-scan --slow --timeout 600               # exhaustive poll\n"
            "  wb-cli serial wb-scan --bootloader --port /dev/ttyRS485-1\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--slow",
        dest="scan_type",
        action="store_const",
        const="standard",
        help="exhaustive UART-combo poll (web UI's «Медленное сканирование»)",
    )
    mode.add_argument(
        "--bootloader",
        dest="scan_type",
        action="store_const",
        const="bootloader",
        help="look for devices in bootloader mode after a failed fw-update",
    )
    p.set_defaults(scan_type="extended")
    p.add_argument(
        "--port",
        default=None,
        help="serial port path; if set, wb-device-manager scans only that port",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="seconds to wait for completion (default: 60; bump for --type extended)",
    )


def _register_templates(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "templates",
        help="list available wb-mqtt-serial device templates",
        description="Names of every JSON template under /usr/share/wb-mqtt-serial/templates/.",
    )


def _register_template(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "template",
        help="dump one device template (registers, channels, defaults)",
        description="Read a single template file from /usr/share/wb-mqtt-serial/templates/.",
    )
    p.add_argument(
        "template_id",
        help="template file name with or without .json, e.g. `config-wb-mr3`",
    )


def _register_config(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "config",
        help="serial config (/etc/wb-mqtt-serial.conf): list / show one device",
        description=(
            "Inspect what's wired into /etc/wb-mqtt-serial.conf:\n"
            "\n"
            "  (no args)     compact table of every enabled device\n"
            "  <slave_id>    full dict of one device (looks up by slave_id or by\n"
            "                the string `id` field that some templates set)\n"
            "\n"
            "Source of truth for the config layer. For actual firmware-parameter\n"
            "values on the hardware use ``wb-cli serial fw-params``."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "device_id",
        nargs="?",
        default=None,
        help="numeric slave_id or string id; omit to list all",
    )
    p.add_argument(
        "--port",
        default=None,
        help="filter the list to a single serial port path",
    )


def _register_fw_params(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "fw-params",
        help="read / write firmware parameters of one device",
        description=(
            "Read or write the firmware-configurable parameters of one device —\n"
            "every value exposed in the device's template under\n"
            "``device.parameters`` (input modes, channel ranges, calibration, etc.).\n"
            "\n"
            "  fw-params <id>                 read params via driver cache\n"
            "  fw-params <id> --force         read live from hardware (bypass cache)\n"
            "  fw-params <id> k=v k=v ...     write — goes through the config:\n"
            "                                 1) confed Load /etc/wb-mqtt-serial.conf\n"
            "                                 2) patch the device dict\n"
            "                                 3) confed Save → driver reload\n"
            "                                 Persistent across driver restart.\n"
            "  fw-params <id> k=v --force     write straight through the driver\n"
            "                                 (wb-mqtt-serial/device/Set RPC), WITHOUT\n"
            "                                 touching the config. One-shot — value\n"
            "                                 reverts on next driver restart.\n"
            "\n"
            "NOT for slave_id or baud_rate — those are bus-level Modbus registers,\n"
            "not template parameters. (Use ``serial wb-set-slave-id`` / ``wb-set-baud``\n"
            "in a later release, or ``serial send`` raw Modbus FC6 today.)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("device_id", help="numeric slave_id or string id from the serial config")
    p.add_argument(
        "params",
        nargs="*",
        metavar="KEY=VALUE",
        help="parameters to write (positional pairs). Omit to read.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="on read: bypass driver cache. On write: skip config, go straight to device.",
    )


def _register_ports(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "ports",
        help="list active serial ports (wb-mqtt-serial/ports/Load RPC)",
        description=(
            "List every port the wb-mqtt-serial driver is currently serving, "
            "with its UART params. Empty result == driver dropped its config "
            "(usually schema validation); inspect the journal and repair via "
            "`wb-cli confed load/save`."
        ),
    )


def _register_add_devices(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "add-devices",
        help="add discovered (or named) devices to the serial config",
        description=(
            "Append entries to the `devices` list of one port in /etc/wb-mqtt-serial.conf.\n"
            "Required template parameters are filled from template defaults automatically,\n"
            "so the config is always valid after adding. Devices already present (same\n"
            "slave_id on the same port) are silently skipped — safe to re-run.\n"
            "\n"
            "Automatic fixups applied to scan-mode devices before adding:\n"
            "  Baud mismatch — if a device runs at a different speed than the port, its\n"
            "    baud rate is changed to match the port (Modbus reg 110 write).\n"
            "  Address collision — if two devices share a slave_id, the duplicate gets a\n"
            "    free address via Fast Modbus by SN (WB/Onokom devices) or reg 128 write\n"
            "    (standard fallback). Config conflicts (new device at an address already\n"
            "    in config) are resolved the same way.\n"
            "\n"
            "Three modes, in order of precedence:\n"
            "\n"
            "  --device-type + --slave-id\n"
            "      Add a single device by model without scanning. Looks up the template\n"
            "      by device_type and fills required parameters from template defaults.\n"
            "      Example: --device-type WB-MAI6 --slave-id 19\n"
            "\n"
            "  --scan-results JSON\n"
            "      Use an explicit JSON list of devices (output of `wb-cli --json serial\n"
            "      wb-scan` → .data.devices). For scripting and agent use.\n"
            "\n"
            "  (default — no extra flags)\n"
            "      Read the retained wb-device-manager state (result of the last scan).\n"
            "      Run `wb-cli serial wb-scan` or `wb-cli serial wb-scan --slow` first, then\n"
            "      call this command. Slow-scan results (third-party devices) are\n"
            "      picked up without re-scanning.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # scan → add (typical workflow)\n"
            "  wb-cli serial wb-scan\n"
            "  wb-cli serial add-devices --port /dev/ttyRS485-1\n"
            "\n"
            "  # slow scan for third-party devices, then add\n"
            "  wb-cli serial wb-scan --slow --timeout 300\n"
            "  wb-cli serial add-devices --port /dev/ttyRS485-1\n"
            "\n"
            "  # add a single device by model (no scan needed)\n"
            "  wb-cli serial add-devices --port /dev/ttyRS485-1 --device-type WB-MAI6 --slave-id 19\n"
            "\n"
            "  # agent/scripted use\n"
            "  wb-cli --json serial add-devices --port /dev/ttyRS485-1\n"
        ),
    )
    p.add_argument(
        "--port",
        default=None,
        help=(
            "target serial port path (must already exist in the config). "
            "Omit to add to every port the scan results mention (scan modes only); "
            "required with --device-type."
        ),
    )
    p.add_argument(
        "--scan-results",
        default=None,
        help=(
            "explicit JSON list of devices (.data.devices from `wb-cli --json serial wb-scan`); "
            "if omitted, reads the retained state from the last scan"
        ),
    )
    p.add_argument(
        "--device-type",
        default=None,
        help="device_type from the template (e.g. WB-MAI6); requires --slave-id and --port; skips scanning",
    )
    p.add_argument(
        "--slave-id",
        type=int,
        default=None,
        help="Modbus slave address to assign when using --device-type",
    )


def _register_send(sub: argparse._SubParsersAction) -> None:
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
    serial_port.add_uart_args(p, stop_bits_choices=[1, 2])
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
