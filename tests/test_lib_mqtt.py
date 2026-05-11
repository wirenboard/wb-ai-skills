"""Error paths and parsing of wb_cli.lib.mqtt.MqttClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.mqtt import MqttClient


def _shell_returning(rc, stdout="", stderr=""):
    shell = MagicMock()
    shell.run.return_value = (rc, stdout, stderr)
    return shell


def _shell_raising(code: str):
    shell = MagicMock()
    err = WbCliError(code=code, message="x", exit_code=3)
    shell.run.side_effect = err
    return shell


def test_subscribe_parses_tab_separated_lines():
    shell = _shell_returning(0, "topic/a\tvalue-a\ntopic/b\tvalue-b\n")
    result = MqttClient(shell).subscribe("topic/+")
    assert result == [("topic/a", "value-a"), ("topic/b", "value-b")]


def test_subscribe_skips_lines_without_tab():
    shell = _shell_returning(0, "garbage-no-tab\ntopic/a\tv\n")
    result = MqttClient(shell).subscribe("topic/+")
    assert result == [("topic/a", "v")]


def test_subscribe_rc27_with_empty_stdout_is_silent_timeout():
    # mosquitto_sub -W returns 27 on timeout. With no payload we treat it as
    # "no retained data", returning []; nothing should raise.
    shell = _shell_returning(27, "", "")
    assert MqttClient(shell).subscribe("topic/never") == []


def test_subscribe_rc27_with_data_returns_data():
    shell = _shell_returning(27, "t\tv\n", "")
    assert MqttClient(shell).subscribe("topic/+") == [("t", "v")]


def test_subscribe_broker_down_when_rc_nonzero_and_no_stdout():
    shell = _shell_returning(1, "", "Connection refused")
    with pytest.raises(WbCliError) as exc:
        MqttClient(shell).subscribe("topic/+")
    assert exc.value.code == "MQTT_BROKER_DOWN"


def test_subscribe_translates_fs_not_found_to_broker_down():
    with pytest.raises(WbCliError) as exc:
        MqttClient(_shell_raising("FS_NOT_FOUND")).subscribe("topic/+")
    assert exc.value.code == "MQTT_BROKER_DOWN"


def test_subscribe_translates_shell_timeout_to_mqtt_timeout():
    with pytest.raises(WbCliError) as exc:
        MqttClient(_shell_raising("TIMEOUT")).subscribe("topic/+")
    assert exc.value.code == "MQTT_TIMEOUT"


def test_publish_passes_retain_flag_when_set():
    shell = _shell_returning(0)
    MqttClient(shell).publish("topic/x", "v", retain=True)
    cmd = shell.run.call_args.args[0]
    assert "-r" in cmd


def test_publish_without_retain_omits_flag():
    shell = _shell_returning(0)
    MqttClient(shell).publish("topic/x", "v")
    cmd = shell.run.call_args.args[0]
    assert "-r" not in cmd


def test_publish_broker_down_on_nonzero_rc():
    shell = _shell_returning(1, "", "boom")
    with pytest.raises(WbCliError) as exc:
        MqttClient(shell).publish("topic/x", "v")
    assert exc.value.code == "MQTT_PUBLISH_FAILED"


def test_publish_translates_fs_not_found_to_broker_down():
    with pytest.raises(WbCliError) as exc:
        MqttClient(_shell_raising("FS_NOT_FOUND")).publish("topic/x", "v")
    assert exc.value.code == "MQTT_BROKER_DOWN"
