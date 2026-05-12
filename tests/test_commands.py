"""Tests for command plugins with mocked handles."""

# pylint: disable=protected-access

from __future__ import annotations

import argparse
import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from wb_cli.commands.audit import AuditPlugin
from wb_cli.commands.cloud import CloudPlugin
from wb_cli.commands.confed import ConfedPlugin
from wb_cli.commands.history import HistoryPlugin
from wb_cli.commands.job_cmd import JobPlugin
from wb_cli.commands.modbus._plugin import ModbusPlugin
from wb_cli.commands.modbus_fw import ModbusFwPlugin
from wb_cli.commands.mqtt_cmd import MqttPlugin
from wb_cli.commands.rules import RulesPlugin
from wb_cli.commands.serial_debug import SerialDebugPlugin
from wb_cli.commands.snapshot import SnapshotPlugin
from wb_cli.context import CliContext
from wb_cli.errors import WbCliError
from wb_cli.lib.controller import ControllerInfo


def _ctx(**overrides):  # pylint: disable=protected-access
    """Create a CliContext with mocked handles."""
    args = overrides.pop("args", argparse.Namespace(quiet=False))
    ctx = CliContext(args, quiet=False)
    ctx._mqtt = overrides.pop("mqtt", MagicMock())
    ctx._rpc = overrides.pop("rpc", MagicMock())
    ctx._systemd = overrides.pop("systemd", MagicMock())
    ctx._journal = overrides.pop("journal", MagicMock())
    ctx._shell = overrides.pop("shell", MagicMock())
    ctx._job = overrides.pop("job", MagicMock())
    ctx._controller = overrides.pop("controller", MagicMock())
    return ctx


# --- audit ---


def test_audit_ok(controller_root: Path):
    ctx = _ctx(controller=ControllerInfo(root=controller_root))
    ctx.systemd.list_failed.return_value = []
    result = AuditPlugin().dispatch(ctx)
    assert result["ok"] is True


def test_audit_with_failures(controller_root: Path):
    ctx = _ctx(controller=ControllerInfo(root=controller_root))
    ctx.systemd.list_failed.return_value = [{"unit": "bad.service"}]
    result = AuditPlugin().dispatch(ctx)
    assert result["ok"] is False


# --- cloud ---


def test_cloud_active():
    ctx = _ctx()
    ctx.systemd.status.return_value = {
        "ActiveState": "active",
        "SubState": "running",
    }
    result = CloudPlugin().dispatch(ctx)
    assert result["active_state"] == "active"


def test_cloud_inactive():
    ctx = _ctx()
    ctx.systemd.status.return_value = {"ActiveState": "inactive"}
    with pytest.raises(WbCliError, match="wb-cloud-agent is inactive"):
        CloudPlugin().dispatch(ctx)


# --- mqtt ---


def test_mqtt_read():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="read",
            topic="/devices/test/controls/val",
            timeout=5.0,
        )
    )
    ctx.mqtt.subscribe.return_value = [
        ("/devices/test/controls/val", "42"),
    ]
    result = MqttPlugin().dispatch(ctx)
    assert result["payload"] == "42"
    ctx.mqtt.subscribe.assert_called_once_with(
        "/devices/test/controls/val",
        timeout=5.0,
    )


def test_mqtt_write():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="write",
            topic="/t",
            payload="v",
            retain=False,
        )
    )
    result = MqttPlugin().dispatch(ctx)
    assert result["ok"] is True
    ctx.mqtt.publish.assert_called_once_with("/t", "v", retain=False)


def test_mqtt_list():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="list",
            topic="#",
            timeout=5.0,
        )
    )
    ctx.mqtt.subscribe.return_value = [("/a", "1"), ("/b", "2")]
    result = MqttPlugin().dispatch(ctx)
    assert result["count"] == 2


def test_mqtt_sub():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="sub",
            topic="$SYS/#",
            count=2,
            timeout=3.0,
        )
    )
    ctx.mqtt.subscribe_live.return_value = [
        ("$SYS/broker/uptime", "123 seconds"),
        ("$SYS/broker/clients/total", "5"),
    ]
    result = MqttPlugin().dispatch(ctx)
    assert result["count"] == 2
    assert result["messages"][0]["topic"] == "$SYS/broker/uptime"
    ctx.mqtt.subscribe_live.assert_called_once_with("$SYS/#", count=2, timeout=3.0)


# --- devices ---
# Plugin removed in 0.3.0; everything moved to the `dev` plugin
# (see tests/test_dev.py).


# --- confed ---


def test_confed_load():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="load",
            path="/etc/wb-mqtt-serial.conf",
        )
    )
    ctx.rpc.call.return_value = {"ports": []}
    result = ConfedPlugin().dispatch(ctx)
    assert result["path"] == "/etc/wb-mqtt-serial.conf"
    ctx.rpc.call.assert_called_once_with(
        "confed/Editor/Load",
        {"path": "/etc/wb-mqtt-serial.conf"},
    )


def test_confed_save():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="save",
            path="/etc/test.conf",
            content='{"key": "val"}',
        )
    )
    result = ConfedPlugin().dispatch(ctx)
    assert result["ok"] is True


def test_confed_save_invalid_json():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="save",
            path="/etc/test.conf",
            content="not json",
        )
    )
    with pytest.raises(WbCliError, match="not valid JSON"):
        ConfedPlugin().dispatch(ctx)


# --- rules ---


def test_rules_list():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="list",
        )
    )
    ctx.rpc.call.return_value = [{"name": "test.js"}]
    result = RulesPlugin().dispatch(ctx)
    assert result["count"] == 1
    ctx.rpc.call.assert_called_once_with("wbrules/Editor/List", {})


def test_rules_load():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="load",
            name="myrule",
        )
    )
    ctx.rpc.call.return_value = "defineRule(...);"
    result = RulesPlugin().dispatch(ctx)
    assert result["name"] == "myrule"


def test_rules_load_unwraps_envelope():
    """Modern wb-rules wraps source in `{"content": ..., "enabled": ...}` — unwrap it."""
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="load",
            name="myrule",
        )
    )
    ctx.rpc.call.return_value = {"content": "defineRule(...);", "enabled": True}
    result = RulesPlugin().dispatch(ctx)
    assert result["content"] == "defineRule(...);"


def test_rules_name_with_slash():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="load",
            name="dir/rule",
        )
    )
    with pytest.raises(WbCliError, match="must not contain"):
        RulesPlugin().dispatch(ctx)


def test_rules_name_with_js():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="load",
            name="rule.js",
        )
    )
    with pytest.raises(WbCliError, match="without .js"):
        RulesPlugin().dispatch(ctx)


def test_rules_disable_uses_shell_mv():
    """`rules disable` runs `mv .js .js.disabled` — wb-rules Editor rejects non-.js names."""
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="disable",
            name="myrule",
        )
    )
    # test src -> exists (rc=0); test dst -> missing (rc=1); mv -> ok (rc=0).
    ctx.shell.run.side_effect = [(0, "", ""), (1, "", ""), (0, "", "")]
    result = RulesPlugin().dispatch(ctx)
    assert result["from"] == "/etc/wb-rules/myrule.js"
    assert result["to"] == "/etc/wb-rules/myrule.js.disabled"
    mv_call = ctx.shell.run.call_args_list[-1].args[0]
    assert mv_call == ["mv", "/etc/wb-rules/myrule.js", "/etc/wb-rules/myrule.js.disabled"]


def test_rules_enable_uses_shell_mv():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="enable",
            name="myrule",
        )
    )
    ctx.shell.run.side_effect = [(0, "", ""), (1, "", ""), (0, "", "")]
    result = RulesPlugin().dispatch(ctx)
    assert result["from"] == "/etc/wb-rules/myrule.js.disabled"
    assert result["to"] == "/etc/wb-rules/myrule.js"


def test_rules_disable_refuses_if_target_exists():
    """If `.js.disabled` already exists, refuse — don't clobber the user's data."""
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="disable",
            name="myrule",
        )
    )
    # src exists (rc=0); dst already exists (rc=0).
    ctx.shell.run.side_effect = [(0, "", ""), (0, "", "")]
    with pytest.raises(WbCliError) as exc:
        RulesPlugin().dispatch(ctx)
    assert exc.value.code == "RULES_TARGET_EXISTS"


def test_rules_enable_missing_source():
    """Enabling a rule that has no .js.disabled — clear RULES_NOT_FOUND."""
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="enable",
            name="myrule",
        )
    )
    ctx.shell.run.side_effect = [(1, "", "")]  # src missing
    with pytest.raises(WbCliError) as exc:
        RulesPlugin().dispatch(ctx)
    assert exc.value.code == "RULES_NOT_FOUND"


# --- history ---


def test_history_get():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="get",
            channel="wb-adc/A1",
            from_ts=None,
            to_ts=None,
            limit=100,
        )
    )
    ctx.rpc.call.return_value = {"values": [{"v": 1.5}]}
    result = HistoryPlugin().dispatch(ctx)
    assert result["count"] == 1


def test_history_get_from_ts_converted_to_unix_seconds():
    from wb_cli.commands.history import (  # pylint: disable=import-outside-toplevel
        _parse_ts,
    )

    ts = _parse_ts("2026-05-11T00:00:00", "--from")
    assert isinstance(ts, int)
    assert ts > 0


def test_history_get_from_ts_invalid_raises():
    from wb_cli.commands.history import (  # pylint: disable=import-outside-toplevel
        _parse_ts,
    )

    with pytest.raises(WbCliError) as exc:
        _parse_ts("not-a-date", "--from")
    assert exc.value.code == "HISTORY_INVALID_TIMESTAMP"


def test_history_get_passes_unix_ts_to_rpc():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="get",
            channel="wb-adc/A1",
            from_ts="2026-05-11T00:00:00",
            to_ts=None,
            limit=10,
        )
    )
    ctx.rpc.call.return_value = {"values": []}
    HistoryPlugin().dispatch(ctx)
    call_params = ctx.rpc.call.call_args.args[1]
    assert isinstance(call_params["timestamp"]["gt"], int)


def test_history_chart():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="chart",
            channel="wb-adc/A1",
            from_ts=None,
            to_ts=None,
            limit=100,
        )
    )
    ctx.rpc.call.return_value = {"values": [{"v": 1.5}, {"v": 2.0}]}
    result = HistoryPlugin().dispatch(ctx)
    assert "xychart-beta" in result["mermaid"]


# --- snapshot ---


def test_snapshot_save(tmp_path: Path):
    ctx = _ctx(controller=ControllerInfo(root=tmp_path))
    ctx.args = argparse.Namespace(
        quiet=False,
        subcmd="save",
        label="test",
    )
    ctx.systemd.list_failed.return_value = []
    import wb_cli.commands.snapshot as snap_mod  # pylint: disable=import-outside-toplevel

    old_dir = snap_mod._SNAPSHOT_DIR  # pylint: disable=protected-access
    snap_mod._SNAPSHOT_DIR = tmp_path / "snapshots"  # pylint: disable=protected-access
    try:
        result = SnapshotPlugin().dispatch(ctx)
        assert result["label"] == "test"
        assert Path(result["path"]).exists()
    finally:
        snap_mod._SNAPSHOT_DIR = old_dir  # pylint: disable=protected-access


# --- job ---


def test_job_list():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="list",
        )
    )
    ctx.job.list_jobs.return_value = [{"unit": "u1", "label": "test"}]
    result = JobPlugin().dispatch(ctx)
    assert result["count"] == 1


# --- modbus ---


def test_modbus_scan(monkeypatch):
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="scan",
            port="/dev/ttyRS485-1",
            timeout=5.0,
            scan_type="extended",
        )
    )
    ctx.rpc.call.return_value = "Ok"
    final_state = (
        '{"progress": 10, "scanning": true, "is_ext_scan": true, "devices": []}\n'
        '{"progress": 50, "scanning": true, "is_ext_scan": true, "devices": []}\n'
        '{"progress": 100, "scanning": true, "is_ext_scan": true, "devices": ['
        '{"slave_id": 52, "title": "WB-MR6C", "port": {"path": "/dev/ttyRS485-1"}}'
        "]}\n"
    )

    class _FakeProc:
        def __init__(self):
            self.stdout = io.StringIO(final_state)

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

    monkeypatch.setattr(
        "wb_cli.commands.modbus._actions.subprocess.Popen",
        lambda *a, **kw: _FakeProc(),
    )
    # The real _await_scan uses select() on the subprocess fd; with a StringIO
    # stand-in we short-circuit to "always ready" so readline does the work.
    monkeypatch.setattr(
        "wb_cli.commands.modbus._actions.select.select",
        lambda r, w, x, t=None: (r, w, x),
    )
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1


def test_modbus_ports():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="ports",
        )
    )
    ctx.rpc.call.return_value = {"ports": [{"path": "/dev/ttyRS485-1"}]}
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1


def test_modbus_templates():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="templates",
        )
    )
    ctx.shell.run.return_value = (0, "wb-mr6c.json\nwb-msw-v4.json\n", "")
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 2


def test_modbus_template_reads_file_from_disk():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="template",
            template_id="config-wb-mr3",
        )
    )
    ctx.shell.run.return_value = (0, '{"device_type": "WB-MR3"}', "")
    result = ModbusPlugin().dispatch(ctx)
    assert result["template"] == {"device_type": "WB-MR3"}
    cmd = ctx.shell.run.call_args.args[0]
    assert cmd[0] == "cat"
    assert cmd[1].endswith("config-wb-mr3.json")


def test_modbus_template_missing_file():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="template",
            template_id="nonexistent",
        )
    )
    ctx.shell.run.return_value = (1, "", "No such file")
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_TEMPLATE_NOT_FOUND"


def test_modbus_template_invalid_json():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="template",
            template_id="broken",
        )
    )
    ctx.shell.run.return_value = (0, "not-json", "")
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_TEMPLATE_INVALID"


def test_modbus_device_info_finds_device_by_slave_id():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="device-info",
            device_id="5",
        )
    )
    ctx.rpc.call.return_value = {
        "content": {
            "ports": [
                {"path": "/dev/ttyRS485-1", "devices": [{"slave_id": 5, "device_type": "WB-MDM3"}]},
                {"path": "/dev/ttyRS485-2", "devices": []},
            ]
        }
    }
    result = ModbusPlugin().dispatch(ctx)
    assert result["device"]["device_type"] == "WB-MDM3"


def test_modbus_device_info_not_found():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="device-info",
            device_id="999",
        )
    )
    ctx.rpc.call.return_value = {"content": {"ports": []}}
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_DEVICE_NOT_FOUND"


def test_modbus_probe_found():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="probe",
            port="/dev/ttyRS485-1",
            address=2,
        )
    )
    ctx.rpc.call.return_value = {"device_signature": "WBMR6C", "sn": "abc"}
    result = ModbusPlugin().dispatch(ctx)
    assert result["found"] is True
    assert result["result"]["device_signature"] == "WBMR6C"


def test_modbus_probe_empty_response_means_not_found():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="probe",
            port="/dev/ttyRS485-1",
            address=99,
        )
    )
    ctx.rpc.call.return_value = {}
    result = ModbusPlugin().dispatch(ctx)
    assert result["found"] is False
    assert result["result"] is None


def test_modbus_probe_rpc_failure_surfaces_as_not_found():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="probe",
            port="/dev/ttyRS485-1",
            address=2,
        )
    )
    ctx.rpc.call.side_effect = WbCliError(code="RPC_ERROR_RESPONSE", message="boom", exit_code=1)
    result = ModbusPlugin().dispatch(ctx)
    assert result["found"] is False
    assert "boom" in result["error"]


def test_modbus_add_devices_appends_to_target_port():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="add-devices",
            port="/dev/ttyRS485-1",
            scan_results='[{"slave_id": 7, "device_type": "WB-MR6C"}]',
        )
    )
    ctx.rpc.call.side_effect = [
        # Editor/Load
        {
            "content": {
                "ports": [
                    {"path": "/dev/ttyRS485-1", "devices": [{"slave_id": 1}]},
                    {"path": "/dev/ttyRS485-2", "devices": []},
                ]
            }
        },
        # Editor/Save
        {"ok": True},
    ]
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1
    save_call = ctx.rpc.call.call_args_list[1]
    saved_content = save_call.args[1]["content"]
    rs1_devices = next(p for p in saved_content["ports"] if p["path"] == "/dev/ttyRS485-1")["devices"]
    assert {"slave_id": 7, "device_type": "WB-MR6C"} in rs1_devices


def test_modbus_add_devices_unknown_port():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="add-devices",
            port="/dev/ttyNOPE",
            scan_results='[{"slave_id": 1}]',
        )
    )
    ctx.rpc.call.return_value = {"content": {"ports": []}}
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_ADD_PORT_NOT_FOUND"


def test_modbus_add_devices_rejects_invalid_json():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="add-devices",
            port="/dev/ttyRS485-1",
            scan_results="not-json",
        )
    )
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_ADD_INVALID_JSON"


def test_modbus_devices_lists_from_serial_conf():
    """`modbus devices` dumps every enabled device from /etc/wb-mqtt-serial.conf."""
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="devices",
            port=None,
        )
    )
    ctx.rpc.call.return_value = {
        "content": {
            "ports": [
                {
                    "path": "/dev/ttyRS485-1",
                    "devices": [
                        {"slave_id": 4},
                        {"slave_id": 7, "enabled": False},  # skipped
                    ],
                },
                {"path": "/dev/ttyRS485-2", "devices": [{"slave_id": 12}]},
            ]
        }
    }
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 2  # disabled device skipped
    slaves = sorted(d["slave_id"] for d in result["devices"])
    assert slaves == [4, 12]


def test_modbus_devices_filters_by_port():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="devices",
            port="/dev/ttyRS485-2",
        )
    )
    ctx.rpc.call.return_value = {
        "content": {
            "ports": [
                {"path": "/dev/ttyRS485-1", "devices": [{"slave_id": 1}]},
                {"path": "/dev/ttyRS485-2", "devices": [{"slave_id": 2}]},
            ]
        }
    }
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1
    assert result["devices"][0]["slave_id"] == 2


# --- modbus-fw ---


def _fw_check_args(slave_id=None, port=None):
    """Common Namespace for `modbus-fw check`."""
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


def test_modbus_fw_check_single():
    """With a slave_id, check probes just that device."""
    ctx = _ctx(args=_fw_check_args(slave_id=4, port="/dev/ttyRS485-1"))
    ctx.rpc.call.return_value = {
        "fw": "1.20.0",
        "available_fw": "1.21.3",
        "can_update": True,
        "bootloader": "1.0.0",
        "available_bootloader": "1.0.0",
    }
    result = ModbusFwPlugin().dispatch(ctx)
    assert result["slave_id"] == 4
    assert result["can_update"] is True
    method, params = ctx.rpc.call.call_args.args[0], ctx.rpc.call.call_args.args[1]
    assert method == "wb-device-manager/fw-update/GetFirmwareInfo"
    assert params["slave_id"] == 4
    assert params["port"]["path"] == "/dev/ttyRS485-1"


def test_modbus_fw_check_bulk_walks_serial_conf():
    """Without a slave_id, bulk-check walks every device from the serial config."""
    ctx = _ctx(args=_fw_check_args(slave_id=None, port=None))

    serial_conf_payload = {
        "content": {
            "ports": [
                {
                    "path": "/dev/ttyRS485-1",
                    "devices": [{"slave_id": 4}, {"slave_id": 7}],
                }
            ]
        }
    }

    def _call(method, params, **_kw):  # pylint: disable=unused-argument
        if method == "confed/Editor/Load":
            return serial_conf_payload
        if method == "wb-device-manager/fw-update/GetFirmwareInfo":
            return {"fw": "1.0", "available_fw": "1.0", "can_update": False}
        raise AssertionError(f"unexpected rpc call: {method}")

    ctx.rpc.call.side_effect = _call
    result = ModbusFwPlugin().dispatch(ctx)
    assert result["count"] == 2
    assert {row["slave_id"] for row in result["devices"]} == {4, 7}
    assert all("can_update" in row for row in result["devices"])


def test_modbus_fw_check_bulk_attaches_per_device_error():
    """A per-device RPC failure becomes an `error` field instead of aborting bulk-check."""
    ctx = _ctx(args=_fw_check_args(slave_id=None, port=None))
    serial_conf_payload = {
        "content": {
            "ports": [
                {
                    "path": "/dev/ttyRS485-1",
                    "devices": [{"slave_id": 4}, {"slave_id": 7}],
                }
            ]
        }
    }

    calls = {"n": 0}

    def _call(method, params, **_kw):  # pylint: disable=unused-argument
        if method == "confed/Editor/Load":
            return serial_conf_payload
        if method == "wb-device-manager/fw-update/GetFirmwareInfo":
            calls["n"] += 1
            if params["slave_id"] == 4:
                raise WbCliError(code="RPC_TIMEOUT", message="no answer", exit_code=3)
            return {"fw": "1.0", "available_fw": "1.0", "can_update": False}
        raise AssertionError(f"unexpected rpc call: {method}")

    ctx.rpc.call.side_effect = _call
    result = ModbusFwPlugin().dispatch(ctx)
    assert calls["n"] == 2  # both devices probed
    by_slave = {row["slave_id"]: row for row in result["devices"]}
    assert by_slave[4]["error"] == "no answer"
    assert by_slave[7]["can_update"] is False


def _fw_update_args(slave_id=None, port=None, all_flag=False):
    return argparse.Namespace(
        quiet=False,
        subcmd="update",
        slave_id=slave_id,
        port=port,
        baud=9600,
        parity="N",
        data_bits=8,
        stop_bits=2,
        software_type="firmware",
        all=all_flag,
        wait=False,
    )


def test_modbus_fw_update_bulk_requires_all_flag():
    """Bulk update without --all is refused — flashing every device is destructive."""
    ctx = _ctx(args=_fw_update_args(slave_id=None, all_flag=False))
    with pytest.raises(WbCliError) as exc:
        ModbusFwPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_FW_BULK_NEEDS_FLAG"


def test_modbus_fw_update_bulk_skips_up_to_date_devices():
    """Bulk update queues only devices with `can_update=true`; others go to `skipped`."""
    ctx = _ctx(args=_fw_update_args(slave_id=None, all_flag=True))
    serial_conf_payload = {
        "content": {
            "ports": [
                {
                    "path": "/dev/ttyRS485-1",
                    "devices": [{"slave_id": 4}, {"slave_id": 7}],
                }
            ]
        }
    }

    def _call(method, params, **_kw):  # pylint: disable=unused-argument
        if method == "confed/Editor/Load":
            return serial_conf_payload
        if method == "wb-device-manager/fw-update/GetFirmwareInfo":
            return {"can_update": params["slave_id"] == 7, "fw": "1.0", "available_fw": "1.1"}
        if method == "wb-device-manager/fw-update/Update":
            return {"ok": True}
        raise AssertionError(f"unexpected rpc call: {method}")

    ctx.rpc.call.side_effect = _call
    result = ModbusFwPlugin().dispatch(ctx)
    assert result["count"] == 1
    assert result["queued"][0]["slave_id"] == 7
    assert result["skipped"][0]["slave_id"] == 4


def test_modbus_fw_update_single_passes_software_type():
    """Single-device update forwards software_type to the RPC."""
    ctx = _ctx(args=_fw_update_args(slave_id=4, port="/dev/ttyRS485-1", all_flag=False))
    ctx.args.software_type = "bootloader"
    ctx.rpc.call.return_value = {"ok": True}
    result = ModbusFwPlugin().dispatch(ctx)
    assert result["type"] == "bootloader"
    assert result["ok"] is True
    method, params = ctx.rpc.call.call_args.args[0], ctx.rpc.call.call_args.args[1]
    assert method == "wb-device-manager/fw-update/Update"
    assert params["type"] == "bootloader"


# --- serial-debug ---


def test_serial_debug(monkeypatch):
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            port="/dev/ttyRS485-1",
            seconds=10,
        )
    )
    ctx.journal.read.return_value = [{"MESSAGE": "debug line"}]
    monkeypatch.setattr("wb_cli.commands.serial_debug.countdown", lambda *a, **kw: None)
    result = SerialDebugPlugin().dispatch(ctx)
    assert result["port"] == "/dev/ttyRS485-1"
    assert result["count"] == 1
    assert ctx.mqtt.publish.call_count == 2


def test_serial_debug_restores_debug_off_when_journal_raises(monkeypatch):
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            port="/dev/ttyRS485-1",
            seconds=10,
        )
    )
    monkeypatch.setattr("wb_cli.commands.serial_debug.countdown", lambda *a, **kw: None)
    ctx.journal.read.side_effect = WbCliError(code="JOURNAL_UNAVAILABLE", message="oops", exit_code=3)
    with pytest.raises(WbCliError):
        SerialDebugPlugin().dispatch(ctx)
    # Both publishes must have fired: enable (1) and the restore in finally (0).
    assert ctx.mqtt.publish.call_count == 2
    last_call = ctx.mqtt.publish.call_args_list[-1]
    assert last_call.args[1] == "0"
