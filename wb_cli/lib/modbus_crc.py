"""Modbus CRC-16 utility shared between commands."""

from __future__ import annotations

import struct


def modbus_crc16(data: bytes) -> bytes:
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
