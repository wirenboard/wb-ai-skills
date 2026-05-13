"""Tests for command plugins with mocked handles."""

# pylint: disable=protected-access

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from wb_cli.commands.audit import AuditPlugin
from wb_cli.commands.cloud import CloudPlugin
from wb_cli.commands.confed import ConfedPlugin
from wb_cli.commands.history import HistoryPlugin
from wb_cli.commands.job_cmd import JobPlugin
from wb_cli.commands.modbus_fw import ModbusFwPlugin
from wb_cli.commands.mqtt_cmd import MqttPlugin
from wb_cli.commands.rules import RulesPlugin
from wb_cli.commands.serial._actions import _parse_hex_msg
from wb_cli.commands.serial._plugin import SerialPlugin as ModbusPlugin
from wb_cli.commands.serial_debug import SerialDebugPlugin
from wb_cli.commands.snapshot import SnapshotPlugin
from wb_cli.context import CliContext
from wb_cli.errors import WbCliError
from wb_cli.lib.controller import ControllerInfo
from wb_cli.lib.modbus_crc import modbus_crc16 as _modbus_crc16


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


def test_modbus_scan():
    ctx = _scan_ctx()
    ctx.rpc.call_watch.side_effect = _make_call_watch(
        [
            '{"progress": 10, "scanning": true, "is_ext_scan": true, "devices": []}',
            '{"progress": 50, "scanning": true, "is_ext_scan": true, "devices": []}',
            '{"progress": 100, "scanning": true, "is_ext_scan": true, "devices": ['
            '{"slave_id": 52, "title": "WB-MR6C", "port": {"path": "/dev/ttyRS485-1"}}]}',
            '{"progress": 0, "scanning": false, "is_ext_scan": true, "devices": ['
            '{"slave_id": 52, "title": "WB-MR6C", "port": {"path": "/dev/ttyRS485-1"}}]}',
        ]
    )
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1
    assert result["completed"] is True


def test_modbus_scan_has_add_hints_when_devices_found():
    """Single-port scan: hints list shows the all-ports form first, then the explicit --port form."""
    ctx = _scan_ctx(port="/dev/ttyRS485-1")
    ctx.rpc.call_watch.side_effect = _make_call_watch(
        [
            '{"progress": 50, "scanning": true, "is_ext_scan": true, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 2}}]}',
            '{"progress": 0, "scanning": false, "is_ext_scan": true, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 2}}]}',
        ]
    )
    result = ModbusPlugin().dispatch(ctx)
    assert result.get("add_hints") == [
        "wb-cli serial add-devices",
        "wb-cli serial add-devices --port /dev/ttyRS485-1",
    ]


def test_modbus_scan_add_hints_multi_port():
    """Multi-port scan: hints list shows the all-ports form, then one entry per port."""
    ctx = _scan_ctx()
    ctx.rpc.call_watch.side_effect = _make_call_watch(
        [
            '{"progress": 50, "scanning": true, "is_ext_scan": true, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 2}},'
            '{"port": {"path": "/dev/ttyRS485-2"}, "cfg": {"slave_id": 7}}]}',
            '{"progress": 0, "scanning": false, "is_ext_scan": true, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 2}},'
            '{"port": {"path": "/dev/ttyRS485-2"}, "cfg": {"slave_id": 7}}]}',
        ]
    )
    result = ModbusPlugin().dispatch(ctx)
    assert result.get("add_hints") == [
        "wb-cli serial add-devices",
        "wb-cli serial add-devices --port /dev/ttyRS485-1",
        "wb-cli serial add-devices --port /dev/ttyRS485-2",
    ]


def test_modbus_scan_no_add_hints_when_no_devices():
    ctx = _scan_ctx()
    ctx.rpc.call_watch.side_effect = _make_call_watch(
        [
            '{"progress": 100, "scanning": true, "is_ext_scan": true, "devices": []}',
            '{"progress": 0, "scanning": false, "is_ext_scan": true, "devices": []}',
        ]
    )
    result = ModbusPlugin().dispatch(ctx)
    assert "add_hints" not in result


def test_modbus_scan_completes_on_scanning_false():
    """The transition scanning=true → scanning=false from wb-device-manager
    signals completion regardless of how progress moves in between."""
    ctx = _scan_ctx()
    ctx.rpc.call_watch.side_effect = _make_call_watch(
        [
            '{"progress": 100, "scanning": true, "is_ext_scan": true, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 3}}]}',
            '{"progress": 0, "scanning": false, "is_ext_scan": true, "devices": ['
            '{"port": {"path": "/dev/ttyRS485-1"}, "cfg": {"slave_id": 3}}]}',
        ]
    )
    result = ModbusPlugin().dispatch(ctx)
    assert result["completed"] is True


def test_modbus_scan_timeout_no_state_hint_mentions_daemon():
    """When wb-device-manager publishes nothing, hint must point at it."""
    ctx = _scan_ctx(timeout=0.01)
    # call_watch delivers no messages → completed=False, hint about daemon
    ctx.rpc.call_watch.side_effect = _make_call_watch([])
    result = ModbusPlugin().dispatch(ctx)
    assert result["completed"] is False
    assert "wb-device-manager" in result.get("hint", "")


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


def test_modbus_templates(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "wb-mr6c.json").write_text("{}", encoding="utf-8")
    (pkg_dir / "wb-msw-v4.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.templates.SEARCH_DIRS",
        (pkg_dir,),
    )
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="templates",
        )
    )
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 2
    assert result["templates"] == ["wb-mr6c.json", "wb-msw-v4.json"]


def test_modbus_template_reads_file_from_disk(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "config-wb-mr3.json").write_text('{"device_type": "WB-MR3"}', encoding="utf-8")
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.templates.SEARCH_DIRS",
        (pkg_dir,),
    )
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="template",
            template_id="config-wb-mr3",
        )
    )
    result = ModbusPlugin().dispatch(ctx)
    assert result["template"] == {"device_type": "WB-MR3"}


def test_modbus_template_missing_file(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.templates.SEARCH_DIRS",
        (pkg_dir,),
    )
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="template",
            template_id="nonexistent",
        )
    )
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_TEMPLATE_NOT_FOUND"


def test_modbus_template_invalid_json(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "broken.json").write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.templates.SEARCH_DIRS",
        (pkg_dir,),
    )
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="template",
            template_id="broken",
        )
    )
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_TEMPLATE_INVALID"


def test_serial_config_single_finds_device_by_slave_id():
    """`serial config <slave_id>` returns one device from /etc/wb-mqtt-serial.conf."""
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="config",
            device_id="5",
            port=None,
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


def test_serial_config_single_not_found():
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="config",
            device_id="999",
            port=None,
        )
    )
    ctx.rpc.call.return_value = {"content": {"ports": []}}
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_DEVICE_NOT_FOUND"


_SCAN_DEV_7 = {
    "port": {"path": "/dev/ttyRS485-1"},
    "cfg": {"slave_id": 7, "baud_rate": 9600, "parity": "N", "data_bits": 8, "stop_bits": 2},
    "configured_device_type": "WB-MR6C",
    "device_signature": "WBMR6C",
    "sn": "12345",
}

_TEMPLATE_MR6C = '{"device_type": "WB-MR6C", "device": {"parameters": []}}'
_PORT_RS1 = {"path": "/dev/ttyRS485-1", "baud_rate": 9600, "parity": "N", "data_bits": 8, "stop_bits": 2}


def _add_ctx(*, port="/dev/ttyRS485-1", scan_results=None, device_type=None, slave_id=None):
    return _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="add-devices",
            port=port,
            scan_results=scan_results,
            device_type=device_type,
            slave_id=slave_id,
        )
    )


def _conf_with_rs1(existing_devices=None):
    return {
        "content": {
            "ports": [
                {**_PORT_RS1, "devices": existing_devices or []},
                {"path": "/dev/ttyRS485-2", "devices": []},
            ]
        }
    }


def test_modbus_add_devices_appends_to_target_port():
    ctx = _add_ctx(scan_results=f"[{__import__('json').dumps(_SCAN_DEV_7)}]")
    # shell.run: grep (template search) → not found, no cat needed
    ctx.shell.run.return_value = (1, "", "")
    ctx.rpc.call.side_effect = [_conf_with_rs1([{"slave_id": 1}]), {"ok": True}]
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1
    assert result["added"][0] == {
        "slave_id": 7,
        "device_type": "WB-MR6C",
        "port": "/dev/ttyRS485-1",
    }
    save_call = ctx.rpc.call.call_args_list[1]
    rs1 = next(p for p in save_call.args[1]["content"]["ports"] if p["path"] == "/dev/ttyRS485-1")
    assert any(d["slave_id"] == 7 and d["device_type"] == "WB-MR6C" for d in rs1["devices"])


def test_modbus_add_devices_unknown_port():
    ctx = _add_ctx(scan_results=f"[{__import__('json').dumps(_SCAN_DEV_7)}]", port="/dev/ttyNOPE")
    ctx.rpc.call.return_value = {"content": {"ports": []}}
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_ADD_PORT_NOT_FOUND"


def test_modbus_add_devices_rejects_invalid_json():
    ctx = _add_ctx(scan_results="not-json")
    ctx.rpc.call.return_value = _conf_with_rs1()
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_ADD_INVALID_JSON"


def test_modbus_add_devices_skips_duplicate_slave_id():
    ctx = _add_ctx(scan_results=f"[{__import__('json').dumps(_SCAN_DEV_7)}]")
    ctx.shell.run.return_value = (1, "", "")
    # slave_id 7 is already in config
    ctx.rpc.call.return_value = _conf_with_rs1([{"slave_id": 7, "device_type": "WB-MR6C"}])
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 0
    assert any(s["slave_id"] == 7 for s in result["skipped"])
    # No save call when nothing is added
    assert ctx.rpc.call.call_count == 1


def test_modbus_add_devices_from_cached_state():
    """No --scan-results: reads retained state via ctx.mqtt.subscribe."""
    ctx = _add_ctx()
    state_json = __import__("json").dumps({"devices": [_SCAN_DEV_7], "progress": 100})

    ctx.mqtt.subscribe.return_value = [("/wb-device-manager/state", state_json)]
    ctx.shell.run.return_value = (1, "", "")  # grep → template not found in either dir
    ctx.rpc.call.side_effect = [_conf_with_rs1(), {"ok": True}]
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1
    assert result["added"][0]["slave_id"] == 7
    assert result.get("warnings")  # template not found → warning


def test_modbus_add_devices_no_state_raises():
    """mqtt.subscribe returns nothing → clear error, not silent hang."""
    ctx = _add_ctx()
    ctx.rpc.call.return_value = _conf_with_rs1()
    ctx.mqtt.subscribe.return_value = []  # no retained state
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_NO_SCAN_STATE"


def test_modbus_add_devices_by_device_type(tmp_path, monkeypatch):
    """--device-type + --slave-id adds without scan, fills required template params."""
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "config-wb-mai6.json").write_text(
        __import__("json").dumps(
            {
                "device_type": "WB-MAI6",
                "device": {
                    "parameters": [
                        {"id": "in1_type", "required": True, "default": 0},
                        {"id": "in2_type", "required": True, "default": 0},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "wb_cli.commands.serial._actions.templates.SEARCH_DIRS",
        (pkg_dir,),
    )
    ctx = _add_ctx(device_type="WB-MAI6", slave_id=19)
    ctx.rpc.call.side_effect = [_conf_with_rs1(), {"ok": True}]
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1
    # --device-type mode adds without the per-row "port" field (single explicit port).
    assert result["added"][0] == {"slave_id": 19, "device_type": "WB-MAI6"}
    save_call = ctx.rpc.call.call_args_list[1]
    rs1 = next(p for p in save_call.args[1]["content"]["ports"] if p["path"] == "/dev/ttyRS485-1")
    added = next(d for d in rs1["devices"] if d["slave_id"] == 19)
    assert added["in1_type"] == 0
    assert added["in2_type"] == 0


def test_modbus_add_devices_device_type_without_slave_id_raises():
    ctx = _add_ctx(device_type="WB-MAI6", slave_id=None)
    ctx.rpc.call.return_value = _conf_with_rs1()
    with pytest.raises(WbCliError) as exc:
        ModbusPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_ADD_MISSING_SLAVE_ID"


def test_modbus_add_devices_warns_when_template_not_found():
    ctx = _add_ctx(device_type="UNKNOWN-XYZ", slave_id=99)
    ctx.shell.run.return_value = (1, "", "")  # grep → not found
    ctx.rpc.call.side_effect = [_conf_with_rs1(), {"ok": True}]
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1  # device IS added
    assert result.get("warnings")


def test_modbus_add_devices_accepts_scan_envelope():
    """--scan-results can be the full {data: {devices: [...]}} envelope."""
    envelope = json.dumps({"data": {"devices": [_SCAN_DEV_7]}})
    ctx = _add_ctx(scan_results=envelope)
    ctx.shell.run.return_value = (1, "", "")
    ctx.rpc.call.side_effect = [_conf_with_rs1(), {"ok": True}]
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1


_SCAN_DEV_7_HS = {
    "port": {"path": "/dev/ttyRS485-1"},
    "cfg": {"slave_id": 7, "baud_rate": 115200, "parity": "N", "data_bits": 8, "stop_bits": 2},
    "configured_device_type": "WB-MR6C",
    "device_signature": "WBMR6C",
    "sn": "12345",
}


def test_modbus_add_devices_changes_baud_to_port_speed():
    """Device at 115200 on a 9600 port → FC6 write to reg 110, then add without baud override."""
    scan = json.dumps([_SCAN_DEV_7_HS])
    ctx = _add_ctx(scan_results=scan)
    ctx.shell.run.return_value = (1, "", "")  # template not found
    # calls: Load, port/Load (baud change), Save
    ctx.rpc.call.side_effect = [_conf_with_rs1(), {"response": ""}, {"ok": True}]
    result = ModbusPlugin().dispatch(ctx)

    assert result["count"] == 1
    assert result["added"][0]["baud_changed"] == "115200 → 9600"

    baud_change_call = ctx.rpc.call.call_args_list[1]
    assert baud_change_call.args[0] == "wb-mqtt-serial/port/Load"
    params = baud_change_call.args[1]
    assert params["baud_rate"] == 115200  # talks to device at its current speed
    assert params["path"] == "/dev/ttyRS485-1"
    # Frame: slave=7 FC6 reg=110(0x6E) val=96(0x60) — 9600//100
    assert params["msg"].startswith("070600")
    assert params["msg"][6:10] == "6e00"  # reg 110, value hi byte 0

    save_call = ctx.rpc.call.call_args_list[2]
    rs1 = next(p for p in save_call.args[1]["content"]["ports"] if p["path"] == "/dev/ttyRS485-1")
    added = next(d for d in rs1["devices"] if d["slave_id"] == 7)
    assert "baud_rate" not in added  # no per-device override — port baud matches now


def test_modbus_add_devices_skips_when_baud_change_fails():
    """If FC6 baud change RPC fails, device is skipped with a warning."""
    scan = json.dumps([_SCAN_DEV_7_HS])
    ctx = _add_ctx(scan_results=scan)
    ctx.shell.run.return_value = (1, "", "")
    # baud change raises → device skipped, no Save call
    ctx.rpc.call.side_effect = [
        _conf_with_rs1(),
        WbCliError(code="RPC_NO_REPLY", message="port busy"),
    ]
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 0
    assert any("could not change baud" in w for w in result.get("warnings", []))
    assert ctx.rpc.call.call_count == 2  # Load + failed port/Load, no Save


_SCAN_DEV_7B = {
    "port": {"path": "/dev/ttyRS485-1"},
    "cfg": {"slave_id": 7, "baud_rate": 9600, "parity": "N", "data_bits": 8, "stop_bits": 2},
    "configured_device_type": None,
    "device_signature": "WBMAO4",
    "sn": "99999",
}

_SCAN_DEV_7B_NO_SN = {
    "port": {"path": "/dev/ttyRS485-1"},
    "cfg": {"slave_id": 7, "baud_rate": 9600, "parity": "N", "data_bits": 8, "stop_bits": 2},
    "configured_device_type": None,
    "device_signature": "THIRD-PARTY",
    "sn": None,
}


def test_modbus_add_devices_resolves_bus_collision_via_sn():
    """Two scan devices same slave_id → second gets new address via Fast Modbus by SN."""
    scan = json.dumps([_SCAN_DEV_7, _SCAN_DEV_7B])
    ctx = _add_ctx(scan_results=scan)
    ctx.shell.run.return_value = (1, "", "")  # no template
    # calls: Load, port/Load (SN reassign), Save
    ctx.rpc.call.side_effect = [_conf_with_rs1(), {"response": ""}, {"ok": True}]
    result = ModbusPlugin().dispatch(ctx)

    assert result["count"] == 2
    added_ids = {e["slave_id"] for e in result["added"]}
    assert 7 in added_ids
    assert len(added_ids) == 2  # second device got a different id

    reassigned = next(e for e in result["added"] if "slave_id_changed" in e)
    assert reassigned["slave_id_changed"].startswith("7 →")

    # pre-pass call: Fast Modbus by SN — FD 46 08 + SN(99999) in big-endian
    sn_call = ctx.rpc.call.call_args_list[1]
    assert sn_call.args[0] == "wb-mqtt-serial/port/Load"
    msg = sn_call.args[1]["msg"]
    assert msg.startswith("fd4608")  # Fast Modbus prefix


def test_modbus_add_devices_bus_collision_no_sn_warns_and_skips():
    """Physical collision without SN — cannot use standard write (unsafe), warn and skip duplicate."""
    scan = json.dumps([_SCAN_DEV_7, _SCAN_DEV_7B_NO_SN])
    ctx = _add_ctx(scan_results=scan)
    ctx.shell.run.return_value = (1, "", "")
    ctx.rpc.call.side_effect = [_conf_with_rs1(), {"ok": True}]  # Load + Save (only first device added)
    result = ModbusPlugin().dispatch(ctx)

    assert result["count"] == 1  # only the first (non-duplicate) device added
    assert any("physical address collision" in w for w in result.get("warnings", []))


def test_modbus_add_devices_config_conflict_reassigns_via_standard_modbus():
    """Scan finds new device at slave_id already in config (different type) → reassign via reg 128."""
    # Config has slave_id=7 as WB-MR6C; scan finds a different device at slave_id=7
    scan_dev = {
        "port": {"path": "/dev/ttyRS485-1"},
        "cfg": {"slave_id": 7, "baud_rate": 9600, "parity": "N", "data_bits": 8, "stop_bits": 2},
        "configured_device_type": None,  # not matched to existing config
        "device_signature": "WBMAO4",
        "sn": None,
    }
    scan = json.dumps([scan_dev])
    ctx = _add_ctx(scan_results=scan)
    ctx.shell.run.return_value = (1, "", "")
    existing = [{"slave_id": 7, "device_type": "WB-MR6C"}]
    # calls: Load, port/Load (reg 128 write to reassign), Save
    ctx.rpc.call.side_effect = [_conf_with_rs1(existing), {"response": ""}, {"ok": True}]
    result = ModbusPlugin().dispatch(ctx)

    assert result["count"] == 1
    added = result["added"][0]
    assert added["slave_id"] != 7  # got a free address
    assert "slave_id_changed" in added
    assert added["slave_id_changed"].startswith("7 →")

    reg128_call = ctx.rpc.call.call_args_list[1]
    msg = reg128_call.args[1]["msg"]
    # Frame: 07 06 00 80 <new_id_hi> <new_id_lo> + CRC — starts with 070600 80
    assert msg[:8] == "07060080"


def test_modbus_devices_lists_from_serial_conf():
    """`modbus devices` dumps every enabled device from /etc/wb-mqtt-serial.conf."""
    ctx = _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="config",
            device_id=None,
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
            subcmd="config",
            device_id=None,
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


def _fw_update_args(slave_id=None, port=None, all_flag=False, background=False, output=None):
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
        background=background,
        output=output,
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


def test_modbus_fw_update_background_requires_output():
    """--background without --output is refused with a clear error."""
    ctx = _ctx(args=_fw_update_args(slave_id=5, port="/dev/ttyRS485-1", background=True, output=None))
    with pytest.raises(WbCliError) as exc:
        ModbusFwPlugin().dispatch(ctx)
    assert exc.value.code == "MODBUS_FW_OUTPUT_REQUIRED"


def test_modbus_fw_update_background_schedules_job(tmp_path):
    """--background schedules `wb-cli modbus-fw update --wait ... > <out>` via ctx.job.run.

    Verifies the generated command line: shell-quotes --port / --output, includes
    --wait inside the job (so the job blocks until the actual flash finishes),
    and returns the job unit name in the envelope.
    """
    out = tmp_path / "fw.json"
    ctx = _ctx(
        args=_fw_update_args(
            slave_id=5,
            port="/dev/ttyRS485-1",
            background=True,
            output=str(out),
        )
    )
    ctx.job.run.return_value = {"unit": "wb-cli-job-modbus-fw-update-1", "log": "/tmp/foo.log"}
    result = ModbusFwPlugin().dispatch(ctx)
    assert result["unit"] == "wb-cli-job-modbus-fw-update-1"
    assert result["output"] == str(out)
    assert result["background"] is True
    cmd = ctx.job.run.call_args.args[1]
    assert "wb-cli --json modbus-fw update 5" in cmd
    assert "--port /dev/ttyRS485-1" in cmd
    assert "--wait" in cmd
    assert f"> {out}" in cmd


def test_modbus_fw_update_background_all_flag_passed_through(tmp_path):
    """`--all` in background mode is propagated into the generated command."""
    out = tmp_path / "fw.json"
    ctx = _ctx(
        args=_fw_update_args(
            slave_id=None,
            port=None,
            all_flag=True,
            background=True,
            output=str(out),
        )
    )
    ctx.job.run.return_value = {"unit": "wb-cli-job-modbus-fw-update-2", "log": "/tmp/bar.log"}
    ModbusFwPlugin().dispatch(ctx)
    cmd = ctx.job.run.call_args.args[1]
    assert "wb-cli --json modbus-fw update" in cmd
    assert "--all" in cmd
    assert "--wait" in cmd


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


# ---------------------------------------------------------------------------
# serial send
# ---------------------------------------------------------------------------


def _serial_send_ctx(msg="FD 46 01", add_modbus_crc=True, response_size=10, baud=9600):
    return _ctx(
        args=argparse.Namespace(
            quiet=False,
            subcmd="send",
            port="/dev/ttyRS485-1",
            baud=baud,
            parity="N",
            data_bits=8,
            stop_bits=2,
            msg=msg,
            add_modbus_crc=add_modbus_crc,
            response_size=response_size,
            response_timeout=500,
            frame_timeout=20,
            total_timeout=5000,
        )
    )


def test_serial_send_builds_correct_rpc_params():
    ctx = _serial_send_ctx(msg="FD 46 01", add_modbus_crc=True, response_size=10)
    ctx.rpc.call.return_value = {"response": "fd460313900ccedc"}
    ModbusPlugin().dispatch(ctx)

    call_args = ctx.rpc.call.call_args
    params = call_args.args[1]
    assert params["protocol"] == "raw"
    assert params["format"] == "HEX"
    assert params["response_size"] == 10
    assert params["path"] == "/dev/ttyRS485-1"
    # CRC is appended: FD 46 01 + 2 CRC bytes = 5 bytes = 10 hex chars
    assert params["msg"].startswith("fd4601")
    assert len(params["msg"]) == 10


def test_serial_send_crc_correct():
    """CRC of FD 46 01 must be 13 90 (from protocol docs example)."""
    data = _parse_hex_msg("FD 46 01")
    crc = _modbus_crc16(data)
    assert crc == bytes([0x13, 0x90])


def test_serial_send_no_crc():
    ctx = _serial_send_ctx(msg="fd4601", add_modbus_crc=False, response_size=0)
    ctx.rpc.call.return_value = {"response": ""}
    ModbusPlugin().dispatch(ctx)

    params = ctx.rpc.call.call_args.args[1]
    assert params["msg"] == "fd4601"


def test_serial_send_returns_request_and_response():
    ctx = _serial_send_ctx(msg="FD 46 01", add_modbus_crc=True, response_size=10)
    ctx.rpc.call.return_value = {"response": "fd4603001eb3700ccedc"}
    result = ModbusPlugin().dispatch(ctx)

    assert "request" in result
    assert "response" in result
    assert result["response"] == "fd4603001eb3700ccedc"


def test_serial_send_render_human():
    plugin = ModbusPlugin()
    result = {
        "port": "/dev/ttyRS485-1",
        "request": "fd460113 90".replace(" ", ""),
        "response": "fd460300020b860ccedc",
    }
    out = plugin.render(result)
    assert out.startswith("→ FD 46 01")
    assert "←" in out


def test_serial_send_render_no_response():
    plugin = ModbusPlugin()
    result = {"port": "/dev/ttyRS485-1", "request": "fd4601", "response": ""}
    out = plugin.render(result)
    assert "no response" in out.lower()


def test_serial_send_invalid_hex_raises():
    with pytest.raises(ValueError):
        _parse_hex_msg("ZZ ZZ")
