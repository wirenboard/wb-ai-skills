"""Tests for wb_cli.lib.serial_conf (shared parsing of /etc/wb-mqtt-serial.conf)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib import serial_conf


def _ctx_with_config(content):
    """Build a ctx whose rpc returns `content` wrapped in confed's envelope."""
    ctx = MagicMock()
    ctx.rpc.call.return_value = {"content": content, "schema": {}}
    return ctx


def test_load_config_unwraps_content():
    payload = {"ports": []}
    ctx = _ctx_with_config(payload)
    assert serial_conf.load_config(ctx) == payload
    ctx.rpc.call.assert_called_once_with(
        "confed/Editor/Load",
        {"path": "/etc/wb-mqtt-serial.conf"},
    )


def test_load_config_accepts_unwrapped_dict():
    ctx = MagicMock()
    ctx.rpc.call.return_value = {"ports": [{"path": "/dev/ttyRS485-1"}]}
    assert serial_conf.load_config(ctx)["ports"][0]["path"] == "/dev/ttyRS485-1"


def test_load_config_rejects_non_dict():
    ctx = MagicMock()
    ctx.rpc.call.return_value = "garbage"
    with pytest.raises(WbCliError, match="not a JSON object"):
        serial_conf.load_config(ctx)


def test_iter_devices_inherits_port_uart():
    """A device without explicit UART keys inherits them from its port."""
    content = {
        "ports": [
            {
                "path": "/dev/ttyRS485-1",
                "baud_rate": 9600,
                "parity": "N",
                "data_bits": 8,
                "stop_bits": 2,
                "devices": [
                    {"slave_id": 4, "device_type": "wb-mao4"},
                ],
            }
        ]
    }
    devs = list(serial_conf.iter_devices(content))
    assert len(devs) == 1
    assert devs[0]["slave_id"] == 4
    assert devs[0]["port_path"] == "/dev/ttyRS485-1"
    assert devs[0]["port"]["baud_rate"] == 9600
    assert devs[0]["port"]["parity"] == "N"
    assert devs[0]["port"]["stop_bits"] == 2


def test_iter_devices_device_overrides_port():
    """A device-level UART key overrides the port-level default."""
    content = {
        "ports": [
            {
                "path": "/dev/ttyRS485-1",
                "baud_rate": 9600,
                "parity": "N",
                "data_bits": 8,
                "stop_bits": 2,
                "devices": [
                    {"slave_id": 7, "device_type": "wb-mr6c", "baud_rate": 115200, "parity": "E"},
                ],
            }
        ]
    }
    devs = list(serial_conf.iter_devices(content))
    assert devs[0]["port"]["baud_rate"] == 115200
    assert devs[0]["port"]["parity"] == "E"
    # Untouched keys still come from the port.
    assert devs[0]["port"]["stop_bits"] == 2


def test_iter_devices_skips_disabled():
    """``enabled: false`` devices are excluded — they never speak on the bus."""
    content = {
        "ports": [
            {
                "path": "/dev/ttyRS485-1",
                "devices": [
                    {"slave_id": 1, "enabled": False},
                    {"slave_id": 2, "enabled": True},
                    {"slave_id": 3},  # enabled is implicit
                ],
            }
        ]
    }
    ids = [d["slave_id"] for d in serial_conf.iter_devices(content)]
    assert ids == [2, 3]


def test_list_devices_filters_by_port():
    content = {
        "ports": [
            {"path": "/dev/ttyRS485-1", "devices": [{"slave_id": 1}]},
            {"path": "/dev/ttyRS485-2", "devices": [{"slave_id": 2}]},
        ]
    }
    result = serial_conf.list_devices(content, port="/dev/ttyRS485-2")
    assert len(result) == 1
    assert result[0]["slave_id"] == 2


def test_list_devices_no_filter_returns_all():
    content = {
        "ports": [
            {"path": "/dev/ttyRS485-1", "devices": [{"slave_id": 1}, {"slave_id": 2}]},
        ]
    }
    assert len(serial_conf.list_devices(content)) == 2


def test_iter_devices_normalizes_code_baud_rate():
    """A device-level baud stored as a register code (real / 100) is expanded.

    WB templates write the override as 96 / 1152; the RPC schema wants the
    real rate (9600 / 115200).
    """
    content = {
        "ports": [
            {
                "path": "/dev/ttyRS485-1",
                "baud_rate": 9600,
                "devices": [
                    {"slave_id": 97, "device_type": "tpl1_wb_mao4", "baud_rate": 1152},
                    {"slave_id": 28, "device_type": "WB-MCM8", "baud_rate": 96},
                ],
            }
        ]
    }
    devs = list(serial_conf.iter_devices(content))
    assert devs[0]["port"]["baud_rate"] == 115200
    assert devs[1]["port"]["baud_rate"] == 9600


def test_iter_devices_keeps_real_baud_rate():
    """A real baud rate (already in the enum) passes through untouched."""
    content = {
        "ports": [
            {
                "path": "/dev/ttyRS485-1",
                "baud_rate": 9600,
                "devices": [
                    {"slave_id": 7, "device_type": "wb-mr6c", "baud_rate": 115200},
                    {"slave_id": 8, "device_type": "wb-mr6c"},  # inherits 9600
                ],
            }
        ]
    }
    devs = list(serial_conf.iter_devices(content))
    assert devs[0]["port"]["baud_rate"] == 115200
    assert devs[1]["port"]["baud_rate"] == 9600


def test_iter_devices_coerces_string_slave_id():
    """slave_id stored as a string is coerced to int for the RPC schema."""
    content = {
        "ports": [
            {
                "path": "/dev/ttyRS485-1",
                "devices": [
                    {"slave_id": "73", "device_type": "wb-mr6c"},
                    {"slave_id": 42, "device_type": "wb-mdm3"},
                ],
            }
        ]
    }
    devs = list(serial_conf.iter_devices(content))
    assert devs[0]["slave_id"] == 73
    assert isinstance(devs[0]["slave_id"], int)
    assert devs[1]["slave_id"] == 42


def test_iter_devices_empty_content():
    assert not list(serial_conf.iter_devices({}))
    assert not list(serial_conf.iter_devices({"ports": []}))
