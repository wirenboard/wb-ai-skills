"""Error paths and parsing of wb_cli.lib.mqtt.MqttClient."""

from __future__ import annotations

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.mqtt import MqttClient


def test_subscribe_parses_tab_separated_lines(shell_returning):
    shell = shell_returning(0, "topic/a\tvalue-a\ntopic/b\tvalue-b\n")
    result = MqttClient(shell).subscribe("topic/+")
    assert result == [("topic/a", "value-a"), ("topic/b", "value-b")]


def test_subscribe_skips_lines_without_tab(shell_returning):
    shell = shell_returning(0, "garbage-no-tab\ntopic/a\tv\n")
    assert MqttClient(shell).subscribe("topic/+") == [("topic/a", "v")]


def test_subscribe_rc27_with_empty_stdout_is_silent_timeout(shell_returning):
    # mosquitto_sub -W returns 27 on timeout. No payload -> empty result,
    # nothing should raise.
    assert not MqttClient(shell_returning(27, "", "")).subscribe("topic/never")


def test_subscribe_rc27_with_data_returns_data(shell_returning):
    assert MqttClient(shell_returning(27, "t\tv\n", "")).subscribe("topic/+") == [("t", "v")]


def test_subscribe_broker_down_when_rc_nonzero_and_no_stdout(shell_returning):
    shell = shell_returning(1, "", "Connection refused")
    with pytest.raises(WbCliError) as exc:
        MqttClient(shell).subscribe("topic/+")
    assert exc.value.code == "MQTT_BROKER_DOWN"


def test_subscribe_translates_fs_not_found_to_broker_down(shell_raising):
    with pytest.raises(WbCliError) as exc:
        MqttClient(shell_raising("FS_NOT_FOUND")).subscribe("topic/+")
    assert exc.value.code == "MQTT_BROKER_DOWN"


def test_subscribe_translates_shell_timeout_to_mqtt_timeout(shell_raising):
    with pytest.raises(WbCliError) as exc:
        MqttClient(shell_raising("TIMEOUT")).subscribe("topic/+")
    assert exc.value.code == "MQTT_TIMEOUT"


def test_publish_passes_retain_flag_when_set(shell_returning):
    shell = shell_returning(0)
    MqttClient(shell).publish("topic/x", "v", retain=True)
    cmd = shell.run.call_args.args[0]
    assert "-r" in cmd


def test_publish_without_retain_omits_flag(shell_returning):
    shell = shell_returning(0)
    MqttClient(shell).publish("topic/x", "v")
    cmd = shell.run.call_args.args[0]
    assert "-r" not in cmd


def test_publish_failed_on_nonzero_rc(shell_returning):
    shell = shell_returning(1, "", "boom")
    with pytest.raises(WbCliError) as exc:
        MqttClient(shell).publish("topic/x", "v")
    assert exc.value.code == "MQTT_PUBLISH_FAILED"


def test_publish_translates_fs_not_found_to_broker_down(shell_raising):
    with pytest.raises(WbCliError) as exc:
        MqttClient(shell_raising("FS_NOT_FOUND")).publish("topic/x", "v")
    assert exc.value.code == "MQTT_BROKER_DOWN"
