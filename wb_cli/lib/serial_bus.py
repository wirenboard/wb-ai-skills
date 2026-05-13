"""Bus-level writes against WB Common Modbus Registers.

Both ``serial wb-set-slave-id`` / ``serial wb-set-baud`` (user-facing) and
``serial add-devices`` (its baud-fixup / address-collision recovery)
issue the same three writes — FC6 reg 128, FC6 reg 110, Fast Modbus FC6
by SN of reg 128. Centralised here so the byte layouts live in one
place and both flows speak the same RPC.

Each helper returns the RPC reply dict on success and propagates
``WbCliError`` on failure. ``serial add-devices`` wraps the calls in
its own ``try`` to convert errors into "device unreachable" warnings;
the user-facing commands surface the error verbatim.
"""

from __future__ import annotations

from typing import Any, Dict

from wb_cli.lib import modbus_frame, serial_port


def change_slave_id_standard(rpc, port: Dict[str, Any], current_id: int, new_id: int) -> Dict[str, Any]:
    """Standard Modbus FC6 write of reg 128. Unsafe under physical collisions."""
    frame = modbus_frame.fc6_write(current_id, modbus_frame.REG_SLAVE_ID, new_id)
    return serial_port.raw_send(rpc, port, msg=frame, response_size=8)


def change_slave_id_by_sn(rpc, port: Dict[str, Any], sn: int, new_id: int) -> Dict[str, Any]:
    """WB Fast Modbus FC6 by SN write of reg 128. Safe under address collisions."""
    frame = modbus_frame.fast_modbus_fc6_by_sn(sn, modbus_frame.REG_SLAVE_ID, new_id)
    return serial_port.raw_send(rpc, port, msg=frame, response_size=14)


def change_baud(rpc, port: Dict[str, Any], slave_id: int, new_baud: int) -> Dict[str, Any]:
    """FC6 write of reg 110 (baud / 100). Speak at the device's *current* baud."""
    frame = modbus_frame.fc6_write(slave_id, modbus_frame.REG_BAUD, new_baud // 100)
    return serial_port.raw_send(rpc, port, msg=frame, response_size=8)
