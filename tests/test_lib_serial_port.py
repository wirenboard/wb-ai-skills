"""Tests for ``wb_cli.lib.serial_port``."""

# pylint: disable=duplicate-code
# Several tests spell out the canonical {path, baud_rate, parity, data_bits,
# stop_bits} dict — same shape lives in test_lib_serial_conf for unrelated
# fixtures. That literal overlap is not a real duplication.

from __future__ import annotations

from unittest.mock import MagicMock

from wb_cli.lib import serial_port


def test_port_params_default():
    assert serial_port.port_params("/dev/ttyRS485-1") == {
        "path": "/dev/ttyRS485-1",
        "baud_rate": 9600,
        "parity": "N",
        "data_bits": 8,
        "stop_bits": 2,
    }


def test_port_params_overrides():
    p = serial_port.port_params(
        "/dev/ttyRS485-2",
        baud_rate=115200,
        parity="E",
        data_bits=7,
        stop_bits=1,
    )
    assert p == {
        "path": "/dev/ttyRS485-2",
        "baud_rate": 115200,
        "parity": "E",
        "data_bits": 7,
        "stop_bits": 1,
    }


def test_port_params_from_cfg_inherits_defaults():
    """Missing keys fall back to WB defaults — what wb-mqtt-serial does for devices."""
    cfg = {"baud_rate": 19200}  # no parity / data_bits / stop_bits
    p = serial_port.port_params_from_cfg("/dev/ttyRS485-1", cfg)
    assert p == {
        "path": "/dev/ttyRS485-1",
        "baud_rate": 19200,
        "parity": "N",
        "data_bits": 8,
        "stop_bits": 2,
    }


def test_port_params_from_cfg_handles_none():
    assert serial_port.port_params_from_cfg("/dev/ttyRS485-1", None) == serial_port.port_params(
        "/dev/ttyRS485-1"
    )


def test_raw_send_builds_correct_rpc_call():
    rpc = MagicMock()
    rpc.call.return_value = {"response": "07060080000508A4"}
    port = serial_port.port_params("/dev/ttyRS485-1")
    result = serial_port.raw_send(
        rpc,
        port,
        msg=bytes.fromhex("070600800005"),
        response_size=8,
    )
    assert result == {"response": "07060080000508A4"}
    target, params = rpc.call.call_args.args
    assert target == "wb-mqtt-serial/port/Load"
    # Port shape preserved
    assert params["path"] == "/dev/ttyRS485-1"
    assert params["baud_rate"] == 9600
    # Raw transport markers
    assert params["protocol"] == "raw"
    assert params["format"] == "HEX"
    assert params["msg"] == "070600800005"
    # Default timeouts
    assert params["response_timeout"] == 500
    assert params["frame_timeout"] == 20
    assert params["total_timeout"] == 3000
    # RPC timeout = total_timeout / 1000 + 5
    assert rpc.call.call_args.kwargs["timeout"] == 3000 / 1000.0 + 5.0


def test_raw_send_propagates_timeout_overrides():
    rpc = MagicMock()
    rpc.call.return_value = {"response": ""}
    serial_port.raw_send(
        rpc,
        serial_port.port_params("/dev/ttyRS485-1"),
        msg=b"\xff",
        response_size=0,
        response_timeout_ms=100,
        frame_timeout_ms=5,
        total_timeout_ms=8000,
    )
    _, params = rpc.call.call_args.args
    assert params["response_timeout"] == 100
    assert params["frame_timeout"] == 5
    assert params["total_timeout"] == 8000
    assert rpc.call.call_args.kwargs["timeout"] == 8000 / 1000.0 + 5.0
