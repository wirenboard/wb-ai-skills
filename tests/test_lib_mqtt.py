"""Error paths and parsing of wb_cli.lib.mqtt.MqttClient."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.mqtt import MqttClient

# ---------- subscribe ----------


class _FakeStdout:  # pylint: disable=too-few-public-methods
    def fileno(self):
        return -1


class _FakePopen:
    """Stand-in for subprocess.Popen for mqtt._drain_retained.

    The plugin reads via ``os.read(fd, n)``; we drive that via _install_io().
    ``returncode`` and ``communicate`` are present because the surrounding
    ``subscribe`` calls them.
    """

    def __init__(self, *, returncode=0, stderr=b""):
        self.returncode = returncode
        self._stderr = stderr
        self.stdout = _FakeStdout()

    def terminate(self):
        pass

    def kill(self):
        pass

    def poll(self):
        return None

    def communicate(self, timeout=None):  # pylint: disable=unused-argument
        return (b"", self._stderr)


def _install_io(monkeypatch, chunks, ready_pattern=None):
    """Wire os.read + select.select so subscribe sees the given retained chunks.

    ``chunks``: list of bytes blobs returned by os.read in order; an empty
    blob simulates EOF (Python sees BlockingIOError-equivalent and idle window
    kicks in).
    ``ready_pattern``: list of bools controlling select() readiness; by
    default each chunk corresponds to one ready+read cycle, then
    not-ready forever.
    """
    if ready_pattern is None:
        ready_pattern = [True] * len(chunks) + [False] * 100

    chunk_iter = iter(chunks)
    ready_iter = iter(ready_pattern)

    def fake_select(rlist, _wlist, _xlist, _timeout):
        ready = next(ready_iter, False)
        return (rlist if ready else [], [], [])

    def fake_read(_fd, _n):
        return next(chunk_iter, b"")

    monkeypatch.setattr("wb_cli.lib.mqtt.select.select", fake_select)
    monkeypatch.setattr("wb_cli.lib.mqtt.os.read", fake_read)
    monkeypatch.setattr("wb_cli.lib.mqtt.os.set_blocking", lambda *_a, **_kw: None)


def _install_popen(monkeypatch, proc):
    monkeypatch.setattr("wb_cli.lib.mqtt.subprocess.Popen", lambda *a, **kw: proc)


def test_subscribe_parses_tab_separated_lines(monkeypatch):
    _install_popen(monkeypatch, _FakePopen())
    _install_io(monkeypatch, [b"topic/a\tvalue-a\ntopic/b\tvalue-b\n"])
    assert MqttClient(MagicMock()).subscribe("topic/+", timeout=2.0) == [
        ("topic/a", "value-a"),
        ("topic/b", "value-b"),
    ]


def test_subscribe_handles_chunked_arrival(monkeypatch):
    """Retained lines may arrive in any number of os.read() chunks."""
    _install_popen(monkeypatch, _FakePopen())
    _install_io(monkeypatch, [b"topic/a\tv", b"alue-a\ntopic/b\tvalue-b\n"])
    assert MqttClient(MagicMock()).subscribe("topic/+", timeout=2.0) == [
        ("topic/a", "value-a"),
        ("topic/b", "value-b"),
    ]


def test_subscribe_keeps_spaces_inside_payload(monkeypatch):
    _install_popen(monkeypatch, _FakePopen())
    _install_io(monkeypatch, [b"/devices/wb-mdm3_5/controls/Channel 1 Dimming Level\t30\n"])
    result = MqttClient(MagicMock()).subscribe("topic/+", timeout=2.0)
    assert result == [("/devices/wb-mdm3_5/controls/Channel 1 Dimming Level", "30")]


def test_subscribe_raises_mqtt_timeout_when_nothing_arrives(monkeypatch):
    _install_popen(monkeypatch, _FakePopen())
    _install_io(monkeypatch, [], ready_pattern=[False] * 100)
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


# ---------- subscribe_live ----------


class _FakeLivePopen:
    """Stand-in for subprocess.Popen used by subscribe_live (communicate-based)."""

    def __init__(self, *, stdout=b"", stderr=b"", returncode=0, timeout_on_communicate=False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._timeout = timeout_on_communicate

    def kill(self):
        pass

    def communicate(self, timeout=None):  # pylint: disable=unused-argument
        if self._timeout:
            raise subprocess.TimeoutExpired(cmd="mosquitto_sub", timeout=timeout)
        return (self._stdout, self._stderr)


def _install_live_popen(monkeypatch, proc):
    monkeypatch.setattr("wb_cli.lib.mqtt.subprocess.Popen", lambda *a, **kw: proc)
    monkeypatch.setattr("wb_cli.lib.mqtt.subprocess.TimeoutExpired", subprocess.TimeoutExpired)


def test_subscribe_live_parses_tab_separated_lines(monkeypatch):
    proc = _FakeLivePopen(stdout=b"topic/a\tvalue-a\ntopic/b\tvalue-b\n")
    _install_live_popen(monkeypatch, proc)
    result = MqttClient(MagicMock()).subscribe_live("topic/+", timeout=2.0)
    assert result == [("topic/a", "value-a"), ("topic/b", "value-b")]


def test_subscribe_live_returns_partial_on_timeout(monkeypatch):
    """When communicate times out, kill + second communicate returns partial data."""

    class _PartialPopen(_FakeLivePopen):
        def __init__(self):
            super().__init__(timeout_on_communicate=True)
            self._calls = 0

        def communicate(self, timeout=None):
            self._calls += 1
            if self._calls == 1:
                raise subprocess.TimeoutExpired(cmd="mosquitto_sub", timeout=timeout)
            return (b"topic/x\t99\n", b"")

    proc = _PartialPopen()
    _install_live_popen(monkeypatch, proc)
    result = MqttClient(MagicMock()).subscribe_live("topic/+", timeout=0.1)
    assert result == [("topic/x", "99")]


def test_subscribe_live_empty_result_with_nonzero_rc_raises(monkeypatch):
    proc = _FakeLivePopen(stdout=b"", stderr=b"connection refused", returncode=1)
    _install_live_popen(monkeypatch, proc)
    with pytest.raises(WbCliError) as exc:
        MqttClient(MagicMock()).subscribe_live("topic/+", timeout=1.0)
    assert exc.value.code == "MQTT_BROKER_DOWN"


def test_subscribe_live_broker_down_when_popen_fails(monkeypatch):
    monkeypatch.setattr(
        "wb_cli.lib.mqtt.subprocess.Popen", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError())
    )
    with pytest.raises(WbCliError) as exc:
        MqttClient(MagicMock()).subscribe_live("topic/+", timeout=1.0)
    assert exc.value.code == "MQTT_BROKER_DOWN"


def test_subscribe_live_count_flag_added_to_cmd(monkeypatch):
    captured = {}

    def fake_popen(cmd, **_kw):
        captured["cmd"] = cmd
        return _FakeLivePopen(stdout=b"t\tv\n")

    monkeypatch.setattr("wb_cli.lib.mqtt.subprocess.Popen", fake_popen)
    MqttClient(MagicMock()).subscribe_live("topic/+", count=3, timeout=2.0)
    assert "-C" in captured["cmd"]
    assert "3" in captured["cmd"]


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
