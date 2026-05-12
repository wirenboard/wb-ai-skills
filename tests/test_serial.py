"""Tests for the wb-cli serial command domain.

Covers utilities, dispatch logic, and render paths for all serial subcommands
that are not already exercised in test_commands.py:

  _parse_param_assignments  _required_params_from_template  _find_free_slave_id  _is_done
  device-params  device-set  wb-scan --slow / --bootloader
  render: _devices_table, _add_devices_summary, _render_device_params, _render_device_set
  serial_conf.iter_devices protocol field
  modbus-fw check: device_type column
"""

# pylint: disable=duplicate-code
# Helpers (_ctx, _fake_proc_class, _scan_ctx) mirror test_commands.py on purpose —
# keeping them local avoids coupling the test modules via conftest fixtures.

from __future__ import annotations

import argparse
import io
from unittest.mock import MagicMock

import pytest
from wb_cli.commands.modbus_fw import (
    ModbusFwPlugin,
    _render_check_bulk,
    _render_check_one,
)
from wb_cli.commands.serial._actions import (
    _find_free_slave_id,
    _is_done,
    _parse_param_assignments,
    _required_params_from_template,
)
from wb_cli.commands.serial._plugin import SerialPlugin
from wb_cli.context import CliContext
from wb_cli.errors import WbCliError
from wb_cli.lib import serial_conf

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ctx(**overrides):
    args = overrides.pop("args", argparse.Namespace(quiet=False))
    ctx = CliContext(args, quiet=False)
    ctx._mqtt = overrides.pop("mqtt", MagicMock())  # pylint: disable=protected-access
    ctx._rpc = overrides.pop("rpc", MagicMock())  # pylint: disable=protected-access
    ctx._systemd = overrides.pop("systemd", MagicMock())  # pylint: disable=protected-access
    ctx._journal = overrides.pop("journal", MagicMock())  # pylint: disable=protected-access
    ctx._shell = overrides.pop("shell", MagicMock())  # pylint: disable=protected-access
    ctx._job = overrides.pop("job", MagicMock())  # pylint: disable=protected-access
    ctx._controller = overrides.pop("controller", MagicMock())  # pylint: disable=protected-access
    return ctx


def _conf(  # pylint: disable=too-many-arguments
    slave_id=5,
    device_type="WB-MDM3",
    port_path="/dev/ttyRS485-1",
    baud=9600,
    device_id=None,
    protocol=None,
):
    """Serial config payload with one device wrapped in confed envelope."""
    dev = {"slave_id": slave_id, "device_type": device_type}
    if device_id is not None:
        dev["id"] = device_id
    if protocol is not None:
        dev["protocol"] = protocol
    return {
        "content": {
            "ports": [
                {
                    "path": port_path,
                    "baud_rate": baud,
                    "parity": "N",
                    "data_bits": 8,
                    "stop_bits": 2,
                    "devices": [dev],
                }
            ]
        }
    }


def _fake_proc_class(state_lines: str):
    class _FakeProc:
        def __init__(self):
            self.stdout = io.StringIO(state_lines)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def terminate(self):
            pass

        def wait(self, timeout=None):
            pass

        def kill(self):
            pass

    return _FakeProc


def _scan_ctx(*, port="/dev/ttyRS485-1", timeout=5.0, scan_type="extended"):
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="wb-scan",
            port=port,
            timeout=timeout,
            scan_type=scan_type,
        )
    )
    ctx.rpc.call.return_value = "Ok"
    return ctx


# ---------------------------------------------------------------------------
# _parse_param_assignments
# ---------------------------------------------------------------------------


def test_parse_param_int():
    result = _parse_param_assignments(argparse.Namespace(params=["mode=1"]))
    assert result == {"mode": 1}
    assert isinstance(result["mode"], int)


def test_parse_param_float():
    result = _parse_param_assignments(argparse.Namespace(params=["scale=1.5"]))
    assert result == {"scale": 1.5}
    assert isinstance(result["scale"], float)


def test_parse_param_string_fallback():
    result = _parse_param_assignments(argparse.Namespace(params=["label=hello"]))
    assert result == {"label": "hello"}
    assert isinstance(result["label"], str)


def test_parse_param_multiple():
    result = _parse_param_assignments(argparse.Namespace(params=["a=1", "b=2.5", "c=text"]))
    assert result == {"a": 1, "b": 2.5, "c": "text"}


def test_parse_param_invalid_format_raises():
    with pytest.raises(WbCliError) as exc:
        _parse_param_assignments(argparse.Namespace(params=["noequals"]))
    assert exc.value.code == "SERIAL_INVALID_PARAM"


def test_parse_param_none_returns_empty():
    assert not _parse_param_assignments(argparse.Namespace(params=None))


def test_parse_param_zero_int():
    result = _parse_param_assignments(argparse.Namespace(params=["mode=0"]))
    assert result == {"mode": 0}
    assert isinstance(result["mode"], int)


# ---------------------------------------------------------------------------
# _required_params_from_template
# ---------------------------------------------------------------------------


def test_required_params_list_format():
    template = {
        "device": {
            "parameters": [
                {"id": "mode", "required": True, "default": 0},
                {"id": "delay", "required": False, "default": 100},
                {"id": "label", "required": True, "default": "auto"},
            ]
        }
    }
    result = _required_params_from_template(template)
    assert result == {"mode": 0, "label": "auto"}
    assert "delay" not in result


def test_required_params_dict_format():
    template = {
        "device": {
            "parameters": {
                "mode": {"required": True, "default": 1},
                "delay": {"required": False, "default": 50},
            }
        }
    }
    result = _required_params_from_template(template)
    assert result == {"mode": 1}
    assert "delay" not in result


def test_required_params_no_default_excluded():
    template = {
        "device": {
            "parameters": [
                {"id": "mode", "required": True},  # no default → excluded
            ]
        }
    }
    assert not _required_params_from_template(template)


def test_required_params_empty_device():
    assert not _required_params_from_template({"device": {}})
    assert not _required_params_from_template({})


# ---------------------------------------------------------------------------
# _find_free_slave_id
# ---------------------------------------------------------------------------


def test_find_free_slave_id_empty_set():
    assert _find_free_slave_id(set()) == 1


def test_find_free_slave_id_skips_used():
    assert _find_free_slave_id({1, 2, 3}) == 4


def test_find_free_slave_id_non_contiguous():
    assert _find_free_slave_id({1, 3, 5}) == 2


def test_find_free_slave_id_all_used_returns_none():
    assert _find_free_slave_id(set(range(1, 248))) is None


# ---------------------------------------------------------------------------
# _is_done
# ---------------------------------------------------------------------------


def test_is_done_extended_requires_ext_phase():
    assert _is_done("extended", is_ext=True) is True
    assert _is_done("extended", is_ext=False) is False


def test_is_done_standard_requires_standard_phase():
    assert _is_done("standard", is_ext=False) is True
    assert _is_done("standard", is_ext=True) is False


def test_is_done_bootloader_any_phase():
    assert _is_done("bootloader", is_ext=True) is True
    assert _is_done("bootloader", is_ext=False) is True


# ---------------------------------------------------------------------------
# serial_conf.iter_devices — protocol field
# ---------------------------------------------------------------------------


def test_iter_devices_default_protocol_is_modbus():
    content = {
        "ports": [
            {
                "path": "/dev/ttyRS485-1",
                "devices": [{"slave_id": 1}],
            }
        ]
    }
    devs = list(serial_conf.iter_devices(content))
    assert devs[0]["protocol"] == "modbus"


def test_iter_devices_device_protocol_takes_precedence():
    content = {
        "ports": [
            {
                "path": "/dev/ttyRS485-1",
                "protocol": "modbus",
                "devices": [{"slave_id": 1, "protocol": "mercury23x"}],
            }
        ]
    }
    devs = list(serial_conf.iter_devices(content))
    assert devs[0]["protocol"] == "mercury23x"


def test_iter_devices_port_protocol_inherited():
    content = {
        "ports": [
            {
                "path": "/dev/ttyRS485-1",
                "protocol": "sombus",
                "devices": [{"slave_id": 1}],
            }
        ]
    }
    devs = list(serial_conf.iter_devices(content))
    assert devs[0]["protocol"] == "sombus"


# ---------------------------------------------------------------------------
# device-params: dispatch
# ---------------------------------------------------------------------------


def _device_params_ctx(device_id="5", force=False):
    return _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="device-params",
            device_id=device_id,
            force=force,
        )
    )


def test_device_params_happy_path():
    ctx = _device_params_ctx()
    ctx.rpc.call.side_effect = [
        _conf(),
        {
            "model": "WB-MDM3 v2",
            "fw": {"version": "2.9.0"},
            "parameters": {"output_mode": 0, "relay_delay": 500},
        },
    ]
    result = SerialPlugin().dispatch(ctx)

    assert result["slave_id"] == 5
    assert result["device_type"] == "WB-MDM3"
    assert result["parameters"] == {"output_mode": 0, "relay_delay": 500}

    load_call = ctx.rpc.call.call_args_list[1]
    assert load_call.args[0] == "wb-mqtt-serial/device/LoadConfig"
    p = load_call.args[1]
    assert p["slave_id"] == 5
    assert p["device_type"] == "WB-MDM3"
    assert p["baud_rate"] == 9600
    assert p["path"] == "/dev/ttyRS485-1"
    assert "force" not in p  # force=False → not forwarded


def test_device_params_found_by_string_id():
    """Device can be looked up by the string `id` field in addition to slave_id."""
    ctx = _device_params_ctx(device_id="wb-mdm3-5")
    ctx.rpc.call.side_effect = [_conf(device_id="wb-mdm3-5"), {"parameters": {}}]
    result = SerialPlugin().dispatch(ctx)
    assert result["slave_id"] == 5


def test_device_params_not_found_raises():
    ctx = _device_params_ctx(device_id="999")
    ctx.rpc.call.return_value = {"content": {"ports": []}}
    with pytest.raises(WbCliError) as exc:
        SerialPlugin().dispatch(ctx)
    assert exc.value.code == "SERIAL_DEVICE_NOT_FOUND"


def test_device_params_force_flag_forwarded():
    ctx = _device_params_ctx(force=True)
    ctx.rpc.call.side_effect = [_conf(), {"parameters": {}}]
    SerialPlugin().dispatch(ctx)
    load_call = ctx.rpc.call.call_args_list[1]
    assert load_call.args[1].get("force") is True


def test_device_params_uses_device_uart_override():
    """Device-level baud_rate override is resolved and forwarded to LoadConfig."""
    conf = {
        "content": {
            "ports": [
                {
                    "path": "/dev/ttyRS485-1",
                    "baud_rate": 9600,
                    "parity": "N",
                    "data_bits": 8,
                    "stop_bits": 2,
                    "devices": [{"slave_id": 5, "device_type": "WB-MDM3", "baud_rate": 115200}],
                }
            ]
        }
    }
    ctx = _device_params_ctx()
    ctx.rpc.call.side_effect = [conf, {"parameters": {}}]
    SerialPlugin().dispatch(ctx)
    load_call = ctx.rpc.call.call_args_list[1]
    assert load_call.args[1]["baud_rate"] == 115200


# ---------------------------------------------------------------------------
# device-params: render
# ---------------------------------------------------------------------------


def test_device_params_render_shows_params():
    plugin = SerialPlugin()
    result = {
        "slave_id": 5,
        "device_type": "WB-MDM3",
        "model": "WB-MDM3 v2",
        "fw": {"version": "2.9.0"},
        "parameters": {"output_mode": 0, "relay_delay": 500},
    }
    out = plugin.render(result)
    assert "WB-MDM3" in out
    assert "slave_id=5" in out
    assert "output_mode" in out
    assert "relay_delay" in out
    assert "2.9.0" in out


def test_device_params_render_empty_params():
    plugin = SerialPlugin()
    result = {
        "slave_id": 5,
        "device_type": "WB-MDM3",
        "parameters": {},
    }
    out = plugin.render(result)
    assert "no configurable parameters" in out


def test_device_params_render_no_fw_info():
    """Render does not crash when model/fw are absent."""
    plugin = SerialPlugin()
    result = {
        "slave_id": 5,
        "device_type": "WB-MDM3",
        "parameters": {"mode": 1},
    }
    out = plugin.render(result)
    assert "slave_id=5" in out
    assert "mode" in out


# ---------------------------------------------------------------------------
# device-set: dispatch
# ---------------------------------------------------------------------------


def _device_set_ctx(device_id="5", params=None):
    return _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="device-set",
            device_id=device_id,
            params=params or ["output_mode=1"],
        )
    )


def test_device_set_happy_path():
    ctx = _device_set_ctx(params=["output_mode=1", "relay_delay=500"])
    ctx.rpc.call.side_effect = [_conf(), None]
    result = SerialPlugin().dispatch(ctx)

    assert result["slave_id"] == 5
    assert result["device_type"] == "WB-MDM3"
    assert result["set"] == {"output_mode": 1, "relay_delay": 500}

    set_call = ctx.rpc.call.call_args_list[1]
    assert set_call.args[0] == "wb-mqtt-serial/device/Set"
    p = set_call.args[1]
    assert p["parameters"] == {"output_mode": 1, "relay_delay": 500}
    assert p["slave_id"] == 5
    assert p["device_type"] == "WB-MDM3"


def test_device_set_invalid_param_raises():
    ctx = _device_set_ctx(params=["noequals"])
    ctx.rpc.call.return_value = _conf()
    with pytest.raises(WbCliError) as exc:
        SerialPlugin().dispatch(ctx)
    assert exc.value.code == "SERIAL_INVALID_PARAM"


def test_device_set_int_value():
    ctx = _device_set_ctx(params=["mode=2"])
    ctx.rpc.call.side_effect = [_conf(), None]
    result = SerialPlugin().dispatch(ctx)
    assert result["set"]["mode"] == 2
    assert isinstance(result["set"]["mode"], int)


def test_device_set_float_value():
    ctx = _device_set_ctx(params=["scale=1.5"])
    ctx.rpc.call.side_effect = [_conf(), None]
    result = SerialPlugin().dispatch(ctx)
    assert result["set"]["scale"] == 1.5
    assert isinstance(result["set"]["scale"], float)


def test_device_set_string_value():
    ctx = _device_set_ctx(params=["label=hello"])
    ctx.rpc.call.side_effect = [_conf(), None]
    result = SerialPlugin().dispatch(ctx)
    assert result["set"]["label"] == "hello"
    assert isinstance(result["set"]["label"], str)


def test_device_set_not_found_raises():
    ctx = _device_set_ctx(device_id="999")
    ctx.rpc.call.return_value = {"content": {"ports": []}}
    with pytest.raises(WbCliError) as exc:
        SerialPlugin().dispatch(ctx)
    assert exc.value.code == "SERIAL_DEVICE_NOT_FOUND"


# ---------------------------------------------------------------------------
# device-set: render
# ---------------------------------------------------------------------------


def test_device_set_render():
    plugin = SerialPlugin()
    result = {
        "slave_id": 5,
        "device_type": "WB-MDM3",
        "set": {"output_mode": 1},
    }
    out = plugin.render(result)
    assert "WB-MDM3" in out
    assert "slave_id=5" in out
    assert "output_mode = 1" in out


def test_device_set_render_multiple_params():
    plugin = SerialPlugin()
    result = {
        "slave_id": 5,
        "device_type": "WB-MDM3",
        "set": {"a": 1, "b": 2},
    }
    out = plugin.render(result)
    assert "a = 1" in out
    assert "b = 2" in out


# ---------------------------------------------------------------------------
# wb-scan --slow and --bootloader
# ---------------------------------------------------------------------------


def test_wb_scan_slow_completes_via_standard_phase(monkeypatch):
    """--slow scan completes when is_ext_scan=False reaches 100%."""
    ctx = _scan_ctx(scan_type="standard")
    state = (
        '{"progress": 50, "scanning": true, "is_ext_scan": false, "devices": []}\n'
        '{"progress": 100, "scanning": false, "is_ext_scan": false, "devices": ['
        '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 5}}'
        "]}\n"
    )
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.subprocess.Popen",
        lambda *a, **kw: _fake_proc_class(state)(),
    )
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.select.select",
        lambda r, w, x, t=None: (r, w, x),
    )
    result = SerialPlugin().dispatch(ctx)
    assert result["completed"] is True
    assert result["count"] == 1
    assert result["scan_type"] == "standard"


def test_wb_scan_slow_ignores_extended_phase_done(monkeypatch):
    """--slow: extended-phase progress=100 (is_ext_scan=True) must NOT trigger completion."""
    ctx = _scan_ctx(scan_type="standard", timeout=0.5)
    state = (
        '{"progress": 100, "scanning": false, "is_ext_scan": true, "devices": ['
        '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 5}}'
        "]}\n"
    )
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.subprocess.Popen",
        lambda *a, **kw: _fake_proc_class(state)(),
    )
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.select.select",
        lambda r, w, x, t=None: (r, w, x),
    )
    result = SerialPlugin().dispatch(ctx)
    # ext-phase done doesn't count for --slow; stdout EOF → completed=False
    assert result["completed"] is False


def test_wb_scan_bootloader_completes_regardless_of_phase(monkeypatch):
    """--bootloader: any progress=100 state means done."""
    ctx = _scan_ctx(scan_type="bootloader")
    state = (
        '{"progress": 100, "scanning": false, "is_ext_scan": true, "devices": ['
        '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 11}}'
        "]}\n"
    )
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.subprocess.Popen",
        lambda *a, **kw: _fake_proc_class(state)(),
    )
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.select.select",
        lambda r, w, x, t=None: (r, w, x),
    )
    result = SerialPlugin().dispatch(ctx)
    assert result["completed"] is True
    assert result["count"] == 1


# ---------------------------------------------------------------------------
# render: _devices_table (protocol column)
# ---------------------------------------------------------------------------


def test_devices_render_shows_protocol_column():
    plugin = SerialPlugin()
    result = {
        "devices": [
            {
                "slave_id": 4,
                "device_type": "WB-MR6C",
                "protocol": "modbus",
                "port_path": "/dev/ttyRS485-1",
                "port": {"baud_rate": 9600, "parity": "N", "data_bits": 8, "stop_bits": 2},
            }
        ],
        "count": 1,
    }
    out = plugin.render(result)
    assert "protocol" in out
    assert "modbus" in out


def test_devices_render_non_modbus_protocol():
    plugin = SerialPlugin()
    result = {
        "devices": [
            {
                "slave_id": 4,
                "device_type": "SOME-DEVICE",
                "protocol": "mercury23x",
                "port_path": "/dev/ttyRS485-1",
                "port": {"baud_rate": 9600, "parity": "N", "data_bits": 8, "stop_bits": 2},
            }
        ],
        "count": 1,
    }
    out = plugin.render(result)
    assert "mercury23x" in out


def test_devices_render_missing_protocol_defaults_to_modbus():
    plugin = SerialPlugin()
    result = {
        "devices": [
            {
                "slave_id": 4,
                "device_type": "WB-MR6C",
                "port_path": "/dev/ttyRS485-1",
                "port": {"baud_rate": 9600, "parity": "N", "data_bits": 8, "stop_bits": 2},
            }
        ],
        "count": 1,
    }
    out = plugin.render(result)
    assert "modbus" in out


# ---------------------------------------------------------------------------
# render: _add_devices_summary
# ---------------------------------------------------------------------------


def test_add_devices_summary_nothing_added():
    plugin = SerialPlugin()
    result = {
        "port": "/dev/ttyRS485-1",
        "added": [],
        "skipped": [],
        "count": 0,
    }
    out = plugin.render(result)
    assert "No new devices added" in out


def test_add_devices_summary_skipped():
    plugin = SerialPlugin()
    result = {
        "port": "/dev/ttyRS485-1",
        "added": [],
        "skipped": [7, 12],
        "count": 0,
    }
    out = plugin.render(result)
    assert "Skipped 2" in out


def test_add_devices_summary_added_with_slave_id_change():
    plugin = SerialPlugin()
    result = {
        "port": "/dev/ttyRS485-1",
        "added": [
            {
                "slave_id": 2,
                "device_type": "WB-MR6C",
                "slave_id_changed": "7 → 2",
            }
        ],
        "skipped": [],
        "count": 1,
    }
    out = plugin.render(result)
    assert "Added 1 device(s)" in out
    assert "address: 7 → 2" in out


def test_add_devices_summary_added_with_baud_change():
    plugin = SerialPlugin()
    result = {
        "port": "/dev/ttyRS485-1",
        "added": [
            {
                "slave_id": 7,
                "device_type": "WB-MR6C",
                "baud_changed": "115200 → 9600",
            }
        ],
        "skipped": [],
        "count": 1,
    }
    out = plugin.render(result)
    assert "baud: 115200 → 9600" in out


def test_add_devices_summary_with_warning():
    plugin = SerialPlugin()
    result = {
        "port": "/dev/ttyRS485-1",
        "added": [{"slave_id": 5, "device_type": "UNKNOWN"}],
        "skipped": [],
        "count": 1,
        "warnings": ["slave_id=5: template for 'UNKNOWN' not found"],
    }
    out = plugin.render(result)
    assert "WARNING" in out
    assert "template" in out


# ---------------------------------------------------------------------------
# modbus-fw check: device_type column
# ---------------------------------------------------------------------------


def _fw_check_args_ns(slave_id=None, port=None):
    return argparse.Namespace(
        quiet=False,
        subcmd="check",
        slave_id=slave_id,
        port=port,
        baud=9600,
        parity="N",
        data_bits=8,
        stop_bits=2,
    )


def test_modbus_fw_check_bulk_includes_device_type():
    """Bulk check carries device_type from the serial config into each row."""
    ctx = _ctx(args=_fw_check_args_ns())
    serial_conf_payload = {
        "content": {
            "ports": [
                {
                    "path": "/dev/ttyRS485-1",
                    "devices": [{"slave_id": 4, "device_type": "WB-MR6C"}],
                }
            ]
        }
    }

    def _call(method, _params, **_kw):
        if method == "confed/Editor/Load":
            return serial_conf_payload
        if method == "wb-device-manager/fw-update/GetFirmwareInfo":
            return {
                "fw": "1.0",
                "available_fw": "1.0",
                "can_update": False,
                "bootloader": "1.0",
                "available_bootloader": "1.0",
            }
        raise AssertionError(f"unexpected rpc call: {method}")

    ctx.rpc.call.side_effect = _call
    result = ModbusFwPlugin().dispatch(ctx)
    assert result["devices"][0]["device_type"] == "WB-MR6C"


def test_modbus_fw_check_bulk_device_type_empty_when_missing():
    """Device without device_type in config gets empty string, not None."""
    ctx = _ctx(args=_fw_check_args_ns())
    serial_conf_payload = {
        "content": {
            "ports": [
                {
                    "path": "/dev/ttyRS485-1",
                    "devices": [{"slave_id": 4}],  # no device_type
                }
            ]
        }
    }

    def _call(method, _params, **_kw):
        if method == "confed/Editor/Load":
            return serial_conf_payload
        if method == "wb-device-manager/fw-update/GetFirmwareInfo":
            return {"fw": "1.0", "available_fw": "1.0", "can_update": False}
        raise AssertionError(f"unexpected rpc call: {method}")

    ctx.rpc.call.side_effect = _call
    result = ModbusFwPlugin().dispatch(ctx)
    assert result["devices"][0]["device_type"] == ""


def test_modbus_fw_check_render_single_shows_device_type():
    """Single-device check render includes device_type in the header line."""
    result = {
        "slave_id": 4,
        "device_type": "WB-MR6C",
        "port": "/dev/ttyRS485-1",
        "can_update": False,
        "fw": "1.0",
        "available_fw": "1.0",
        "bootloader": "1.0",
        "available_bootloader": "1.0",
    }
    out = _render_check_one(result)
    assert "WB-MR6C" in out


def test_modbus_fw_check_render_single_no_device_type():
    """Render does not crash when device_type is absent (single-device mode without config lookup)."""
    result = {
        "slave_id": 4,
        "device_type": "",
        "port": "/dev/ttyRS485-1",
        "can_update": True,
        "fw": "1.0",
        "available_fw": "1.1",
        "bootloader": "1.0",
        "available_bootloader": "1.0",
    }
    out = _render_check_one(result)
    assert "slave_id=4" in out


def test_modbus_fw_check_render_bulk_device_type_column():
    """Bulk check render table includes device_type column header and value."""
    rows = [
        {
            "slave_id": 4,
            "device_type": "WB-MR6C",
            "port": "/dev/ttyRS485-1",
            "fw": "1.0",
            "available_fw": "1.0",
            "can_update": False,
            "bootloader": "1.0",
            "available_bootloader": "1.0",
        }
    ]
    out = _render_check_bulk(rows)
    assert "device_type" in out
    assert "WB-MR6C" in out
