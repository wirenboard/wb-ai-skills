"""Tests for ``wb_cli.lib.modbus_frame``."""

from __future__ import annotations

from wb_cli.lib import modbus_frame
from wb_cli.lib.modbus_crc import modbus_crc16


def test_fc6_write_layout_and_crc():
    # FC6 write reg 128 := 5 to slave 7
    frame = modbus_frame.fc6_write(slave_id=7, register=128, value=5)
    # 07 06 00 80 00 05  + CRC
    assert frame.startswith(bytes.fromhex("070600800005"))
    assert len(frame) == 8
    # CRC matches the helper on the PDU
    assert frame[-2:] == modbus_crc16(bytes.fromhex("070600800005"))


def test_fc6_write_baud_reg_110():
    """Common case: write reg 110 (baud abbreviation) to slave 5 at speed 9600 (96)."""
    frame = modbus_frame.fc6_write(slave_id=5, register=110, value=96)
    assert frame.startswith(bytes.fromhex("050600"))  # slave=05 FC=06 reg-hi=00
    assert frame[3:6].hex() == "6e0060"  # reg=110(0x006E) val=96(0x0060) — split across bytes


def test_fast_modbus_pdu_by_sn_envelope():
    """SN=0x00020B86, inner PDU = FC6 write reg 0x0080 := 0x0005."""
    inner = bytes.fromhex("0600800005")
    frame = modbus_frame.fast_modbus_pdu_by_sn(sn=0x00020B86, pdu=inner)
    # FD 46 08 <SN BE 4B> <inner> <CRC>
    assert frame.startswith(bytes.fromhex("FD460800020B86"))
    expected_payload = bytes.fromhex("FD460800020B86") + inner
    assert frame == expected_payload + modbus_crc16(expected_payload)


def test_fast_modbus_fc6_by_sn_matches_manual_envelope():
    """Shortcut equals fast_modbus_pdu_by_sn(sn, struct.pack(>BHH, 0x06, reg, val))."""
    sn, reg, val = 0x12345678, 0x0080, 0x0007
    shortcut = modbus_frame.fast_modbus_fc6_by_sn(sn, reg, val)
    manual = modbus_frame.fast_modbus_pdu_by_sn(
        sn,
        bytes.fromhex("06") + reg.to_bytes(2, "big") + val.to_bytes(2, "big"),
    )
    assert shortcut == manual
