"""Helpers for reading /etc/wb-mqtt-serial.conf through wb-mqtt-confed.

Several plugins (``modbus``, ``modbus-fw``) need the configured list of
Modbus devices together with their full UART parameters. Centralised here
so the parsing of confed's wrapped payload + the per-port / per-device UART
inheritance lives in one place.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from wb_cli.errors import ExitCode, WbCliError

CONFIG_PATH = "/etc/wb-mqtt-serial.conf"

# Fields a device inherits from the parent port if it doesn't override them.
_INHERITED_UART_KEYS = ("baud_rate", "parity", "data_bits", "stop_bits")

# Real baud rates the RPCs accept. A device template stores its baud as the
# Modbus register code (real / 100, e.g. 96 → 9600); normalised below.
_REAL_BAUD_RATES = frozenset(
    {110, 300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400}
)


def _normalize_baud(value: Any) -> Any:
    """Map a Modbus baud register code (real / 100) back to the real rate.

    A value that is already a real rate — or anything unrecognised — is
    returned untouched, so the worst case is the previous pass-through.
    """
    if value in _REAL_BAUD_RATES:
        return value
    if isinstance(value, int) and value * 100 in _REAL_BAUD_RATES:
        return value * 100
    return value


def _normalize_slave_id(value: Any) -> Any:
    """Coerce a slave_id stored as a numeric string (``"73"``) to ``int``.

    wb-mqtt-serial.conf may store slave_id as a string, but the
    wb-device-manager fw-update RPC schema requires an integer. Non-numeric
    values (e.g. a Fast-Modbus SN string) are returned untouched.
    """
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


def load_config(ctx) -> Dict[str, Any]:
    """Return the parsed content of /etc/wb-mqtt-serial.conf.

    Confed wraps the file as ``{"configPath", "content", "schema", ...}``;
    callers want just ``content``. Raises on missing/empty config.
    """
    result = ctx.rpc.call("confed/Editor/Load", {"path": CONFIG_PATH})
    content = result.get("content", result) if isinstance(result, dict) else result
    if not isinstance(content, dict):
        raise WbCliError(
            code="MODBUS_CONFIG_INVALID",
            message=f"{CONFIG_PATH} is not a JSON object",
            details={"path": CONFIG_PATH},
            exit_code=ExitCode.ENVIRONMENT,
        )
    return content


def iter_devices(content: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Yield each configured device with resolved port path and UART params.

    A device may override the port's UART defaults; the yielded dict carries
    the *effective* settings ready to feed back into a Modbus RPC.
    """
    for port in content.get("ports", []) if isinstance(content, dict) else []:
        port_path = port.get("path")
        port_uart = {k: port.get(k) for k in _INHERITED_UART_KEYS if k in port}
        for dev in port.get("devices", []) if isinstance(port, dict) else []:
            if dev.get("enabled") is False:
                continue
            uart = dict(port_uart)
            for k in _INHERITED_UART_KEYS:
                if k in dev:
                    uart[k] = dev[k]
            if "baud_rate" in uart:
                uart["baud_rate"] = _normalize_baud(uart["baud_rate"])
            yield {
                "slave_id": _normalize_slave_id(dev.get("slave_id")),
                "device_type": dev.get("device_type"),
                "id": dev.get("id"),
                "protocol": dev.get("protocol") or port.get("protocol") or "modbus",
                "port_path": port_path,
                "port": {"path": port_path, **uart},
            }


def list_devices(content: Dict[str, Any], *, port: Optional[str] = None) -> List[Dict[str, Any]]:
    """``iter_devices`` materialised, optionally filtered to one port."""
    return [d for d in iter_devices(content) if port is None or d["port_path"] == port]
