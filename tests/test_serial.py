"""Tests for the wb-cli serial command domain.

Covers utilities, dispatch logic, and render paths for all serial subcommands
that are not already exercised in test_commands.py:

  _parse_param_assignments  _required_params_from_template  _find_free_slave_id
  device-params  device-set  wb-scan --slow / --bootloader
  render: _devices_table, _add_devices_summary, _render_device_params, _render_device_set
  serial_conf.iter_devices protocol field
  modbus-fw check: device_type column
"""

# pylint: disable=duplicate-code
# Helpers (_ctx, _scan_ctx) mirror test_commands.py on purpose —
# keeping them local avoids coupling the test modules via conftest fixtures.

from __future__ import annotations

import argparse
from unittest.mock import MagicMock

import pytest
from wb_cli.commands.serial._actions import (
    _find_free_slave_id,
    _parse_param_assignments,
    _required_params_from_template,
    _send_modbus,
    _wb_set_baud,
    _wb_set_slave_id,
)
from wb_cli.commands.serial._plugin import SerialPlugin
from wb_cli.commands.serial._wb_fw import _render_check_bulk, _render_check_one
from wb_cli.commands.serial._wb_fw import dispatch as _wb_fw_dispatch
from wb_cli.context import CliContext
from wb_cli.errors import WbCliError
from wb_cli.lib import serial_conf
from wb_cli.lib.modbus_crc import modbus_crc16

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
    result = _parse_param_assignments(["mode=1"])
    assert result == {"mode": 1}
    assert isinstance(result["mode"], int)


def test_parse_param_float():
    result = _parse_param_assignments(["scale=1.5"])
    assert result == {"scale": 1.5}
    assert isinstance(result["scale"], float)


def test_parse_param_string_fallback():
    result = _parse_param_assignments(["label=hello"])
    assert result == {"label": "hello"}
    assert isinstance(result["label"], str)


def test_parse_param_multiple():
    result = _parse_param_assignments(["a=1", "b=2.5", "c=text"])
    assert result == {"a": 1, "b": 2.5, "c": "text"}


def test_parse_param_invalid_format_raises():
    with pytest.raises(WbCliError) as exc:
        _parse_param_assignments(["noequals"])
    assert exc.value.code == "SERIAL_INVALID_PARAM"


def test_parse_param_none_returns_empty():
    assert not _parse_param_assignments(None)


def test_parse_param_zero_int():
    result = _parse_param_assignments(["mode=0"])
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
    """Build a ctx for `serial fw-params <id>` read flow (no positional params)."""
    return _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="fw-params",
            device_id=device_id,
            params=[],
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


def _fw_params_write_ctx(device_id="5", params=None, force=False):
    """Build a ctx for `serial fw-params <id> k=v...` write flow."""
    return _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="fw-params",
            device_id=device_id,
            params=params if params is not None else ["output_mode=1"],
            force=force,
        )
    )


def test_fw_params_write_through_config_default():
    """Default write path: confed Load → patch device dict → confed Save.

    Persistent: the value survives a driver restart because the config is
    the source of truth.
    """
    ctx = _fw_params_write_ctx(params=["output_mode=1", "relay_delay=500"])
    # iter_devices view (used by _resolve_device_from_config) + raw content
    # (used to mutate the device dict before Save) come from the same
    # confed/Editor/Load call. Patch the latter to return the raw content
    # twice so both code paths see the same data.
    raw_load = _conf()
    # Sequence:
    #   1. confed/Editor/Load — for _resolve_device_from_config (serial_conf.load_config)
    #   2. confed/Editor/Load — for _fw_params_write_via_config
    #   3. confed/Editor/Save — patch persisted
    ctx.rpc.call.side_effect = [raw_load, raw_load, {"ok": True}]
    result = SerialPlugin().dispatch(ctx)

    assert result["slave_id"] == 5
    assert result["device_type"] == "WB-MDM3"
    assert result["set"] == {"output_mode": 1, "relay_delay": 500}
    assert result["via"] == "config"

    save_call = ctx.rpc.call.call_args_list[2]
    assert save_call.args[0] == "confed/Editor/Save"
    saved_dev = next(
        d
        for port in save_call.args[1]["content"]["ports"]
        for d in port.get("devices", [])
        if d.get("slave_id") == 5
    )
    assert saved_dev["output_mode"] == 1
    assert saved_dev["relay_delay"] == 500


def test_fw_params_write_force_goes_through_driver():
    """--force on write: skip the config, drive RPC `wb-mqtt-serial/device/Set` directly.

    One-shot: the value will revert on the next driver restart because the
    config still holds the old value.
    """
    ctx = _fw_params_write_ctx(params=["output_mode=1"], force=True)
    ctx.rpc.call.side_effect = [_conf(), {"ok": True}]
    result = SerialPlugin().dispatch(ctx)

    assert result["set"] == {"output_mode": 1}
    assert result["via"] == "device"

    set_call = ctx.rpc.call.call_args_list[1]
    assert set_call.args[0] == "wb-mqtt-serial/device/Set"
    p = set_call.args[1]
    assert p["parameters"] == {"output_mode": 1}
    assert p["slave_id"] == 5
    assert p["device_type"] == "WB-MDM3"


def test_fw_params_write_invalid_param_raises():
    ctx = _fw_params_write_ctx(params=["noequals"])
    ctx.rpc.call.return_value = _conf()
    with pytest.raises(WbCliError) as exc:
        SerialPlugin().dispatch(ctx)
    assert exc.value.code == "SERIAL_INVALID_PARAM"


def test_fw_params_write_int_value():
    ctx = _fw_params_write_ctx(params=["mode=2"], force=True)
    ctx.rpc.call.side_effect = [_conf(), {"ok": True}]
    result = SerialPlugin().dispatch(ctx)
    assert result["set"]["mode"] == 2
    assert isinstance(result["set"]["mode"], int)


def test_fw_params_write_float_value():
    ctx = _fw_params_write_ctx(params=["scale=1.5"], force=True)
    ctx.rpc.call.side_effect = [_conf(), {"ok": True}]
    result = SerialPlugin().dispatch(ctx)
    assert result["set"]["scale"] == 1.5
    assert isinstance(result["set"]["scale"], float)


def test_fw_params_write_string_value():
    ctx = _fw_params_write_ctx(params=["label=hello"], force=True)
    ctx.rpc.call.side_effect = [_conf(), {"ok": True}]
    result = SerialPlugin().dispatch(ctx)
    assert result["set"]["label"] == "hello"
    assert isinstance(result["set"]["label"], str)


def test_fw_params_write_not_found_raises():
    ctx = _fw_params_write_ctx(device_id="999", force=True)
    ctx.rpc.call.return_value = {"content": {"ports": []}}
    with pytest.raises(WbCliError) as exc:
        SerialPlugin().dispatch(ctx)
    assert exc.value.code == "SERIAL_DEVICE_NOT_FOUND"


# ---------------------------------------------------------------------------
# fw-params write render (same envelope shape `{slave_id, device_type, set}`)
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


def _make_call_watch(state_jsons):
    """Side-effect for ctx.rpc.call_watch: feeds state messages then calls on_tick once."""

    def side_effect(
        target, params=None, *, on_state, on_tick=None, **_kwargs
    ):  # pylint: disable=unused-argument
        for msg in state_jsons:
            on_state(msg)
        if on_tick is not None:
            on_tick()

    return side_effect


def test_wb_scan_slow_completes_on_scanning_false():
    """--slow scan completes when wb-device-manager publishes scanning=false."""
    ctx = _scan_ctx(scan_type="standard")
    ctx.rpc.call_watch.side_effect = _make_call_watch(
        [
            '{"progress": 50, "scanning": true, "is_ext_scan": false, "devices": []}',
            '{"progress": 100, "scanning": true, "is_ext_scan": false, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 5}}]}',
            '{"progress": 0, "scanning": false, "is_ext_scan": false, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 5}}]}',
        ]
    )
    result = SerialPlugin().dispatch(ctx)
    assert result["completed"] is True
    assert result["count"] == 1
    assert result["scan_type"] == "standard"


def test_wb_scan_ignores_initial_idle_state():
    """A `scanning=false` state seen before `scanning=true` is the retained idle
    snapshot and must NOT trigger completion — wait until the scan actually starts."""
    ctx = _scan_ctx(scan_type="standard", timeout=0.5)
    ctx.rpc.call_watch.side_effect = _make_call_watch(
        [
            '{"progress": 0, "scanning": false, "is_ext_scan": true, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 5}}]}'
        ]
    )
    result = SerialPlugin().dispatch(ctx)
    assert result["completed"] is False


def test_wb_scan_bootloader_completes_on_scanning_false():
    """--bootloader: scanning=true → scanning=false means done."""
    ctx = _scan_ctx(scan_type="bootloader")
    ctx.rpc.call_watch.side_effect = _make_call_watch(
        [
            '{"progress": 50, "scanning": true, "is_ext_scan": false, "devices": []}',
            '{"progress": 100, "scanning": false, "is_ext_scan": false, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 11}}]}',
        ]
    )
    result = SerialPlugin().dispatch(ctx)
    assert result["completed"] is True
    assert result["count"] == 1


def test_wb_scan_keeps_devices_through_reset_state():
    """At end of scan, wb-device-manager publishes a reset message with
    ``progress=0, devices=[]`` — that must NOT wipe the accumulated devices."""
    ctx = _scan_ctx(scan_type="extended")
    ctx.rpc.call_watch.side_effect = _make_call_watch(
        [
            '{"progress": 50, "scanning": true, "is_ext_scan": true, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 5}}]}',
            '{"progress": 100, "scanning": true, "is_ext_scan": true, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 5}},'
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 9}}]}',
            # Reset state at end of scan — must not wipe the list.
            '{"progress": 0, "scanning": false, "is_ext_scan": true, "devices": []}',
        ]
    )
    result = SerialPlugin().dispatch(ctx)
    assert result["completed"] is True
    assert result["count"] == 2
    # Progress reported as the last non-zero value, not the reset's 0.
    if not result["completed"]:
        assert result["progress"] == 100


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
        subcmd="wb-fw",
        wb_fw_action="check",
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
    result = _wb_fw_dispatch(ctx)
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
    result = _wb_fw_dispatch(ctx)
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


def test_modbus_fw_check_render_bulk_sanitizes_garbage_cells():
    """ENGO EFAN: 0x0F bytes in fw + S3 404 XML body in available_bootloader must not break the table."""
    s3_404_body = (
        "\n<html>\n<head><title>404 Not Found</title></head>\n"
        "<body>\n<h1>404 Not Found</h1>\n<ul>\n<li>Code: NoSuchKey</li>\n"
        "</ul>\n</body>\n</html>"
    )
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
        },
        {
            "slave_id": 145,
            "device_type": "ENGO EFAN",
            "port": "/dev/ttyRS485-1",
            "fw": "\x0fF",
            "available_fw": "",
            "can_update": True,
            "bootloader": "\x0f",
            "available_bootloader": s3_404_body,
        },
    ]
    out = _render_check_bulk(rows)
    lines = out.splitlines()
    assert len(lines) == 5, f"expected 5 lines, got {len(lines)}: {lines!r}"
    assert "\x0f" not in out
    header_width = len(lines[1])
    for row_line in lines[3:]:
        assert len(row_line) == header_width, (
            f"row width mismatch: {len(row_line)} vs header {header_width} ({row_line!r})"
        )


# ---------------------------------------------------------------------------
# send-modbus: PDU build, response parsing
# ---------------------------------------------------------------------------


def _send_modbus_args(**overrides):
    ns = argparse.Namespace(
        quiet=False,
        subcmd="send-modbus",
        port="/dev/ttyRS485-1",
        baud=9600,
        parity="N",
        data_bits=8,
        stop_bits=2,
        slave=5,
        fc=3,
        reg=110,
        count=1,
        value=None,
        response_timeout=500,
        frame_timeout=20,
        total_timeout=5000,
    )
    for key, val in overrides.items():
        setattr(ns, key, val)
    return ns


def test_send_modbus_fc3_builds_correct_pdu_and_parses_response():
    """FC3 read: request = slave + fc + reg + count + CRC; response payload decoded."""
    ctx = _ctx(args=_send_modbus_args(fc=3, reg=128, count=2))
    # Response: 05 03 04 00 13 12 34 + CRC. Two regs = [0x0013, 0x1234].
    body = bytes.fromhex("05030400131234")
    response_hex = (body + modbus_crc16(body)).hex()
    ctx.rpc.call.return_value = {"response": response_hex}
    result = _send_modbus(ctx)
    assert result["registers"] == [0x0013, 0x1234]
    assert result["fc"] == 3
    assert result["count"] == 2
    # request: slave=05, fc=03, reg=0x0080, count=0x0002, then CRC
    assert result["request"].startswith("050300800002")


def test_send_modbus_fc4_uses_input_register_function_code():
    """FC4 builds a request with fc=04, response parser shape unchanged."""
    ctx = _ctx(args=_send_modbus_args(fc=4, reg=0, count=1))
    body = bytes.fromhex("0504020042")  # slave=5 fc=4 bc=2 val=0x0042
    ctx.rpc.call.return_value = {"response": (body + modbus_crc16(body)).hex()}
    result = _send_modbus(ctx)
    assert result["fc"] == 4
    assert result["registers"] == [0x0042]
    assert result["request"].startswith("05040000")  # slave=05 fc=04 reg=0000


def test_send_modbus_fc6_uses_value_and_returns_8_byte_echo():
    """FC6 write needs --value; expected response is the 8-byte echo."""
    ctx = _ctx(args=_send_modbus_args(fc=6, reg=128, value=19, count=1))
    # FC6 response echoes the request.
    body = bytes.fromhex("0506008000130000")[:6]  # slave fc reg val (6 bytes pre-CRC)
    response = (body + modbus_crc16(body)).hex()
    ctx.rpc.call.return_value = {"response": response}
    result = _send_modbus(ctx)
    assert result["fc"] == 6
    assert result["value"] == 19
    assert "registers" not in result
    # request: slave=05 fc=06 reg=0080 val=0013
    assert result["request"].startswith("050600800013")


def test_send_modbus_fc6_without_value_raises():
    """FC6 without --value is a usage error."""
    ctx = _ctx(args=_send_modbus_args(fc=6, reg=128, value=None))
    with pytest.raises(WbCliError) as exc:
        _send_modbus(ctx)
    assert exc.value.code == "SERIAL_FC6_NEEDS_VALUE"


def test_send_modbus_short_response_returns_empty_register_list():
    """A malformed/truncated response keeps the raw hex but parses to []."""
    ctx = _ctx(args=_send_modbus_args(fc=3, reg=0, count=10))
    ctx.rpc.call.return_value = {"response": "0503"}  # way too short
    result = _send_modbus(ctx)
    assert result["registers"] == []
    assert result["response"] == "0503"


# ---------------------------------------------------------------------------
# wb-set-slave-id / wb-set-baud
# ---------------------------------------------------------------------------


def _wb_set_slave_id_args(**overrides):
    ns = argparse.Namespace(
        quiet=False,
        subcmd="wb-set-slave-id",
        port="/dev/ttyRS485-1",
        baud=9600,
        parity="N",
        data_bits=8,
        stop_bits=2,
        current_id=5,
        new_id=19,
        sn=None,
    )
    for key, val in overrides.items():
        setattr(ns, key, val)
    return ns


def test_wb_set_slave_id_standard_fc6_to_reg_128():
    """Without --sn: standard FC6 write to reg 128 of current_id."""
    ctx = _ctx(args=_wb_set_slave_id_args(current_id=5, new_id=19))
    ctx.rpc.call.return_value = {"response": ""}
    result = _wb_set_slave_id(ctx)
    assert result["via"] == "standard-fc6-reg128"
    assert result["current_id"] == 5
    assert result["new_id"] == 19
    # check the RPC payload
    method, params = ctx.rpc.call.call_args.args[0], ctx.rpc.call.call_args.args[1]
    assert method == "wb-mqtt-serial/port/Load"
    msg = params["msg"]
    # slave=05 fc=06 reg=0080 val=0013 + CRC = 8 bytes hex (16 chars)
    assert msg.startswith("050600800013")
    assert len(msg) == 16


def test_wb_set_slave_id_fast_modbus_by_sn_when_sn_given():
    """With --sn: Fast Modbus FD 46 08 envelope."""
    ctx = _ctx(args=_wb_set_slave_id_args(current_id=5, new_id=19, sn="0x00020B86"))
    ctx.rpc.call.return_value = {"response": ""}
    result = _wb_set_slave_id(ctx)
    assert result["via"] == "fast-modbus-by-sn"
    method, params = ctx.rpc.call.call_args.args[0], ctx.rpc.call.call_args.args[1]
    assert method == "wb-mqtt-serial/port/Load"
    msg = params["msg"]
    # Fast Modbus prefix FD4608 + SN(big-endian 4 bytes) + FC6 reg 128 val 19 + CRC.
    assert msg.startswith("fd460800020b86")
    assert "060080" in msg  # FC6 + reg 0x0080


def test_wb_set_slave_id_invalid_sn_raises():
    ctx = _ctx(args=_wb_set_slave_id_args(sn="not-hex"))
    with pytest.raises(WbCliError) as exc:
        _wb_set_slave_id(ctx)
    assert exc.value.code == "SERIAL_INVALID_HEX"


def _wb_set_baud_args(**overrides):
    ns = argparse.Namespace(
        quiet=False,
        subcmd="wb-set-baud",
        port="/dev/ttyRS485-1",
        baud=9600,
        parity="N",
        data_bits=8,
        stop_bits=2,
        slave_id=5,
        new_baud=115200,
    )
    for key, val in overrides.items():
        setattr(ns, key, val)
    return ns


def test_wb_set_baud_writes_reg_110_with_baud_div_100():
    """FC6 reg 110, value = new_baud / 100 (115200 → 0x0480)."""
    ctx = _ctx(args=_wb_set_baud_args(slave_id=5, new_baud=115200))
    ctx.rpc.call.return_value = {"response": ""}
    result = _wb_set_baud(ctx)
    assert result["new_baud"] == 115200
    assert result["old_baud"] == 9600
    method, params = ctx.rpc.call.call_args.args[0], ctx.rpc.call.call_args.args[1]
    assert method == "wb-mqtt-serial/port/Load"
    msg = params["msg"]
    # slave=05 fc=06 reg=006E val=0480 + CRC
    assert msg.startswith("0506006e0480")


def test_wb_set_baud_speaks_at_current_baud_passed_via_uart_flag():
    """The port baud sent to wb-mqtt-serial is the device's *current* baud (--baud arg)."""
    ctx = _ctx(args=_wb_set_baud_args(slave_id=5, new_baud=9600, baud=115200))
    ctx.rpc.call.return_value = {"response": ""}
    _wb_set_baud(ctx)
    params = ctx.rpc.call.call_args.args[1]
    assert params["baud_rate"] == 115200  # we talk to the device at its current speed


def test_wb_set_baud_rejects_non_100_multiple():
    ctx = _ctx(args=_wb_set_baud_args(new_baud=9601))
    with pytest.raises(WbCliError) as exc:
        _wb_set_baud(ctx)
    assert exc.value.code == "SERIAL_INVALID_BAUD"
