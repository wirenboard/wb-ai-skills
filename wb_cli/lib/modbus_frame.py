"""Modbus / WB Fast Modbus frame builders.

Frames live here so callers don't need to remember byte layouts, struct
formats, or where the CRC goes. Every helper returns the bytes ready to
hand to ``wb-mqtt-serial/port/Load`` with ``protocol: raw``.
"""

from __future__ import annotations

import struct

from wb_cli.lib.modbus_crc import modbus_crc16

# Fast Modbus framing constants (broadcast address + command byte).
_FAST_MODBUS_ADDR = 0xFD
_FAST_MODBUS_CMD = 0x46
_FAST_MODBUS_SUB_PDU_BY_SN = 0x08

# Standard Modbus function codes.
FC_WRITE_SINGLE_REGISTER = 0x06

# WB-specific holding registers (see Common_Modbus_Registers on the wiki).
REG_BAUD = 110
REG_SLAVE_ID = 128


def fc6_write(slave_id: int, register: int, value: int) -> bytes:
    """Standard Modbus FC6 ``write single register``, CRC appended.

    Layout: ``<slave> 06 <reg hi> <reg lo> <val hi> <val lo> <crc lo> <crc hi>``.
    """
    pdu = struct.pack(">BBHH", slave_id, FC_WRITE_SINGLE_REGISTER, register, value)
    return pdu + modbus_crc16(pdu)


def fast_modbus_pdu_by_sn(sn: int, pdu: bytes) -> bytes:
    """WB Fast Modbus envelope targeting a device by 32-bit serial number.

    Wraps ``pdu`` in ``FD 46 08 <SN big-endian> <pdu>`` and appends CRC.
    ``pdu`` is the standard Modbus function bytes (e.g. the ``06 <reg> <val>``
    portion of an FC6 write — without slave_id and without CRC; this envelope
    addresses the device by SN, not by Modbus address).
    """
    payload = (
        bytes([_FAST_MODBUS_ADDR, _FAST_MODBUS_CMD, _FAST_MODBUS_SUB_PDU_BY_SN]) + struct.pack(">I", sn) + pdu
    )
    return payload + modbus_crc16(payload)


def fast_modbus_fc6_by_sn(sn: int, register: int, value: int) -> bytes:
    """Shortcut: Fast Modbus FC6 write of a single register addressed by SN."""
    return fast_modbus_pdu_by_sn(
        sn,
        struct.pack(">BHH", FC_WRITE_SINGLE_REGISTER, register, value),
    )
