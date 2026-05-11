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
from wb_cli.commands.devices import DevicesPlugin
from wb_cli.commands.history import HistoryPlugin
from wb_cli.commands.job_cmd import JobPlugin
from wb_cli.commands.modbus._plugin import ModbusPlugin
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
            human=False,
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
            human=False,
            quiet=False,
            subcmd="list",
            topic="#",
            timeout=5.0,
        )
    )
    ctx.mqtt.subscribe.return_value = [("/a", "1"), ("/b", "2")]
    result = MqttPlugin().dispatch(ctx)
    assert result["count"] == 2


# --- devices ---


def test_devices_list():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
            quiet=False,
            subcmd="list",
        )
    )
    ctx.mqtt.subscribe.return_value = [
        ("/devices/wb-adc/meta/name", "ADCs"),
        ("/devices/wb-adc/meta/driver", "wb-adc"),
        ("/devices/wb-gpio/meta/name", "Discrete I/O"),
        ("/devices/wb-gpio/meta/driver", "wb-gpio"),
    ]
    result = DevicesPlugin().dispatch(ctx)
    assert result["count"] == 2
    ids = [d["id"] for d in result["devices"]]
    assert "wb-adc" in ids


def test_devices_controls():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
            quiet=False,
            subcmd="controls",
            device="wb-adc",
        )
    )
    ctx.mqtt.subscribe.side_effect = [
        [("/devices/wb-adc/controls/A1", "0.5")],
        [],
    ]
    result = DevicesPlugin().dispatch(ctx)
    assert result["count"] == 1


def test_devices_set():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
            quiet=False,
            subcmd="set",
            device="wb-mr6c_52",
            control="K1",
            value="1",
        )
    )
    result = DevicesPlugin().dispatch(ctx)
    assert result["ok"] is True
    ctx.mqtt.publish.assert_called_once_with("/devices/wb-mr6c_52/controls/K1/on", "1")


def test_devices_controls_with_meta():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
            quiet=False,
            subcmd="controls",
            device="wb-gpio",
        )
    )
    ctx.mqtt.subscribe.side_effect = [
        [
            ("/devices/wb-gpio/controls/V_OUT", "1"),
            ("/devices/wb-gpio/controls/D1_IN", "0"),
        ],
        [
            ("/devices/wb-gpio/controls/V_OUT/meta/type", "switch"),
            ("/devices/wb-gpio/controls/V_OUT/meta/readonly", "0"),
            ("/devices/wb-gpio/controls/D1_IN/meta/type", "switch"),
            ("/devices/wb-gpio/controls/D1_IN/meta/readonly", "1"),
        ],
    ]
    result = DevicesPlugin().dispatch(ctx)
    assert result["count"] == 2
    ctrl_vout = next(c for c in result["controls"] if c["name"] == "V_OUT")
    assert ctrl_vout["type"] == "switch"
    assert ctrl_vout["readonly"] is False
    ctrl_d1 = next(c for c in result["controls"] if c["name"] == "D1_IN")
    assert ctrl_d1["readonly"] is True


# --- confed ---


def test_confed_load():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
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
            human=False,
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
            human=False,
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
            human=False,
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
            human=False,
            quiet=False,
            subcmd="load",
            name="myrule",
        )
    )
    ctx.rpc.call.return_value = "defineRule(...);"
    result = RulesPlugin().dispatch(ctx)
    assert result["name"] == "myrule"


def test_rules_name_with_slash():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
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
            human=False,
            quiet=False,
            subcmd="load",
            name="rule.js",
        )
    )
    with pytest.raises(WbCliError, match="without .js"):
        RulesPlugin().dispatch(ctx)


# --- history ---


def test_history_get():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
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


def test_history_chart():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
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
        human=False,
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
            human=False,
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
            human=False,
            quiet=False,
            subcmd="scan",
            port="/dev/ttyRS485-1",
            timeout=5.0,
        )
    )
    ctx.rpc.call.return_value = "Ok"
    final_state = (
        '{"progress": 10, "scanning": true, "devices": []}\n'
        '{"progress": 50, "scanning": true, "devices": []}\n'
        '{"progress": 100, "scanning": true, "devices": ['
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
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 1


def test_modbus_ports():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
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
            human=False,
            quiet=False,
            subcmd="templates",
        )
    )
    ctx.shell.run.return_value = (0, "wb-mr6c.json\nwb-msw-v4.json\n", "")
    result = ModbusPlugin().dispatch(ctx)
    assert result["count"] == 2


# --- serial-debug ---


def test_serial_debug():
    ctx = _ctx(
        args=argparse.Namespace(
            human=False,
            quiet=False,
            port="/dev/ttyRS485-1",
            seconds=10,
        )
    )
    ctx.journal.read.return_value = [{"MESSAGE": "debug line"}]
    result = SerialDebugPlugin().dispatch(ctx)
    assert result["port"] == "/dev/ttyRS485-1"
    assert result["count"] == 1
    # Проверяем что debug включился и выключился
    assert ctx.mqtt.publish.call_count == 2
