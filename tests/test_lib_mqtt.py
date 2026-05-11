"""Error paths and parsing of wb_cli.lib.mqtt.MqttClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.mqtt import MqttClient

# ---------- subscribe ----------


class _FakePopen:
    """Stand-in for subprocess.Popen tailored to mqtt._drain_retained.

    ``lines`` is the retained stream we expect mosquitto_sub to print to
    stdout; once exhausted, the .stdout file behaves like the broker went
    silent — exactly the case `_drain_retained` watches for via select().
    """

    def __init__(self, lines, *, returncode=0, stderr=""):
        self._lines = list(lines)
        self.returncode = returncode
        self._stderr = stderr
        self.stdout = MagicMock()
        self.stdout.readline.side_effect = self._lines + [""]

    def terminate(self):
        pass

    def kill(self):
        pass

    def communicate(self, timeout=None):  # pylint: disable=unused-argument
        return ("", self._stderr)


def _install_popen(monkeypatch, fake_popen):
    monkeypatch.setattr("wb_cli.lib.mqtt.subprocess.Popen", lambda *a, **kw: fake_popen)


def _install_select(monkeypatch, sequence):
    """Drive select.select(): each call pops one (stdout_ready, [], []) value."""
    iterator = iter(sequence)

    def fake_select(rlist, wlist, xlist, timeout=None):  # pylint: disable=unused-argument
        try:
            ready = next(iterator)
        except StopIteration:
            ready = False
        return (rlist if ready else [], [], [])

    monkeypatch.setattr("wb_cli.lib.mqtt.select.select", fake_select)


def test_subscribe_parses_tab_separated_lines(monkeypatch):
    proc = _FakePopen(["topic/a\tvalue-a\n", "topic/b\tvalue-b\n"])
    _install_popen(monkeypatch, proc)
    _install_select(monkeypatch, [True, True, False, False, False, False, False, False])
    result = MqttClient(MagicMock()).subscribe("topic/+", timeout=2.0)
    assert result == [("topic/a", "value-a"), ("topic/b", "value-b")]


def test_subscribe_raises_mqtt_timeout_when_nothing_arrives(monkeypatch):
    proc = _FakePopen([])
    _install_popen(monkeypatch, proc)
    # select never reports ready -> deadline trips, no messages collected.
    _install_select(monkeypatch, [False] * 100)
    with pytest.raises(WbCliError) as exc:
        MqttClient(MagicMock()).subscribe("topic/+", timeout=0.2)
    assert exc.value.code == "MQTT_TIMEOUT"


def test_subscribe_broker_down_when_popen_fails(monkeypatch):
    def boom(*_a, **_kw):
        raise FileNotFoundError("no mosquitto_sub")

    monkeypatch.setattr("wb_cli.lib.mqtt.subprocess.Popen", boom)
    with pytest.raises(WbCliError) as exc:
        MqttClient(MagicMock()).subscribe("topic/+", timeout=1.0)
    assert exc.value.code == "MQTT_BROKER_DOWN"


# ---------- publish ----------


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
