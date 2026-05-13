"""Tests for ``wb_cli.commands.mqtt_debug``."""

# pylint: disable=protected-access,redefined-outer-name

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from wb_cli.commands import mqtt_debug
from wb_cli.commands.mqtt_debug import MqttDebugPlugin
from wb_cli.context import CliContext
from wb_cli.errors import WbCliError


def _ctx(args: argparse.Namespace) -> CliContext:
    ctx = CliContext(args, quiet=False)
    ctx._systemd = MagicMock()
    ctx._journal = MagicMock()
    ctx._shell = MagicMock()
    ctx._job = MagicMock()
    return ctx


@pytest.fixture()
def fake_config(monkeypatch, tmp_path: Path):
    """Redirect the debug config path into a tmp_path so tests don't touch /etc."""
    cfg = tmp_path / "debug-verbose.conf"
    monkeypatch.setattr(mqtt_debug, "_DEBUG_CONFIG_PATH", cfg)
    return cfg


# --- enable / disable ------------------------------------------------------- #


def test_enable_writes_config_and_restarts_mosquitto(fake_config):
    ctx = _ctx(argparse.Namespace(subcmd="enable", quiet=False))
    result = MqttDebugPlugin().dispatch(ctx)
    assert result == {
        "action": "enable",
        "ok": True,
        "verbose_enabled": True,
        "changed": True,
    }
    assert fake_config.exists()
    assert "log_type all" in fake_config.read_text(encoding="utf-8")
    ctx.systemd.restart.assert_called_once_with("mosquitto")


def test_enable_idempotent_when_already_on(fake_config):
    fake_config.write_text("log_type all\n", encoding="utf-8")
    ctx = _ctx(argparse.Namespace(subcmd="enable", quiet=False))
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["changed"] is False
    ctx.systemd.restart.assert_not_called()


def test_disable_removes_config_and_restarts(fake_config):
    fake_config.write_text("log_type all\n", encoding="utf-8")
    ctx = _ctx(argparse.Namespace(subcmd="disable", quiet=False))
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["changed"] is True
    assert not fake_config.exists()
    ctx.systemd.restart.assert_called_once_with("mosquitto")


def test_disable_idempotent_when_already_off(fake_config):  # pylint: disable=unused-argument
    ctx = _ctx(argparse.Namespace(subcmd="disable", quiet=False))
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["changed"] is False
    ctx.systemd.restart.assert_not_called()


# --- status ---------------------------------------------------------------- #


def test_status_reports_enabled_and_active(fake_config):
    fake_config.write_text("log_type all\n", encoding="utf-8")
    ctx = _ctx(argparse.Namespace(subcmd="status", quiet=False))
    ctx.systemd.status.return_value = {"ActiveState": "active"}
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["verbose_enabled"] is True
    assert result["mosquitto_active_state"] == "active"
    assert result["config_path"] == str(fake_config)


def test_status_when_mosquitto_unknown(fake_config):  # pylint: disable=unused-argument
    ctx = _ctx(argparse.Namespace(subcmd="status", quiet=False))
    ctx.systemd.status.side_effect = WbCliError(code="SYSTEMD_UNIT_NOT_FOUND", message="x", exit_code=3)
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["verbose_enabled"] is False
    assert result["mosquitto_active_state"] == "unknown"


# --- capture --------------------------------------------------------------- #


def _capture_args(**overrides):
    base = {
        "subcmd": "capture",
        "quiet": False,
        "seconds": 5,
        "topic": None,  # list[str] | None (action=append)
        "client_id": None,  # list[str] | None (action=append)
        "output": None,
        "background": False,
        "keep_enabled": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _publish_entry(topic="/devices/x/y", client_id="wb-adc", ts="1778654671000000"):
    return {
        "__REALTIME_TIMESTAMP": ts,
        "MESSAGE": f"Received PUBLISH from {client_id} (d0, q1, r0, m1, '{topic}', ... (3 bytes))",
    }


def test_capture_short_inline_enables_and_restores(monkeypatch, fake_config):
    """Default short capture: not enabled → we enable → countdown → parse → restore."""
    monkeypatch.setattr(mqtt_debug, "countdown", lambda *a, **kw: None)
    ctx = _ctx(_capture_args(seconds=2))
    ctx.journal.read.return_value = [_publish_entry()]
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["count"] == 1
    assert result["entries"][0]["topic"] == "/devices/x/y"
    assert result["verbose_was_already_enabled"] is False
    # We toggled on at the start and back off at the end → 2 restarts.
    assert ctx.systemd.restart.call_count == 2
    # And the config file is gone after restore.
    assert not fake_config.exists()


def test_capture_short_inline_when_already_enabled_does_not_disable(monkeypatch, fake_config):
    fake_config.write_text("log_type all\n", encoding="utf-8")
    monkeypatch.setattr(mqtt_debug, "countdown", lambda *a, **kw: None)
    ctx = _ctx(_capture_args(seconds=2))
    ctx.journal.read.return_value = []
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["verbose_was_already_enabled"] is True
    # We did NOT toggle anything → no restarts.
    ctx.systemd.restart.assert_not_called()
    # Config still present.
    assert fake_config.exists()


def test_capture_filters_by_topic(monkeypatch, fake_config):  # pylint: disable=unused-argument
    """Single --topic substring."""
    fake_config.write_text("log_type all\n", encoding="utf-8")
    monkeypatch.setattr(mqtt_debug, "countdown", lambda *a, **kw: None)
    ctx = _ctx(_capture_args(seconds=1, topic=["K1"]))
    ctx.journal.read.return_value = [
        _publish_entry(topic="/devices/wb-mr6c_7/controls/K1/on", client_id="wb-rules"),
        _publish_entry(topic="/devices/wb-adc/controls/V5_0", client_id="wb-adc"),
    ]
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["count"] == 1
    assert "K1" in result["entries"][0]["topic"]
    assert result["topic_filters"] == ["K1"]


def test_capture_multiple_topics_or_match(monkeypatch, fake_config):  # pylint: disable=unused-argument
    """Multiple --topic values: OR-match."""
    fake_config.write_text("log_type all\n", encoding="utf-8")
    monkeypatch.setattr(mqtt_debug, "countdown", lambda *a, **kw: None)
    ctx = _ctx(_capture_args(seconds=1, topic=["K1", "Vin"]))
    ctx.journal.read.return_value = [
        _publish_entry(topic="/devices/wb-mr6c_7/controls/K1/on"),
        _publish_entry(topic="/devices/wb-mr6c_7/controls/K2/on"),
        _publish_entry(topic="/devices/wb-adc/controls/Vin"),
    ]
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["count"] == 2
    assert {e["topic"] for e in result["entries"]} == {
        "/devices/wb-mr6c_7/controls/K1/on",
        "/devices/wb-adc/controls/Vin",
    }


def test_capture_topic_with_space_and_wildcard(monkeypatch, fake_config):  # pylint: disable=unused-argument
    """MQTT-wildcard pattern matches a topic containing spaces."""
    fake_config.write_text("log_type all\n", encoding="utf-8")
    monkeypatch.setattr(mqtt_debug, "countdown", lambda *a, **kw: None)
    ctx = _ctx(
        _capture_args(seconds=1, topic=["/devices/+/controls/Channel 1 Dimming Level/on"]),
    )
    ctx.journal.read.return_value = [
        _publish_entry(topic="/devices/wb-mdm3_5/controls/Channel 1 Dimming Level/on"),
        _publish_entry(topic="/devices/wb-mr6c_7/controls/K1/on"),
    ]
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["count"] == 1
    assert result["entries"][0]["topic"].endswith("Channel 1 Dimming Level/on")


def test_capture_writes_output_file(monkeypatch, fake_config, tmp_path):  # pylint: disable=unused-argument
    fake_config.write_text("log_type all\n", encoding="utf-8")
    monkeypatch.setattr(mqtt_debug, "countdown", lambda *a, **kw: None)
    out = tmp_path / "capture.json"
    ctx = _ctx(_capture_args(seconds=1, output=str(out)))
    ctx.journal.read.return_value = [_publish_entry()]
    MqttDebugPlugin().dispatch(ctx)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["data"]["count"] == 1


def test_capture_too_long_without_background_raises(fake_config):  # pylint: disable=unused-argument
    ctx = _ctx(_capture_args(seconds=mqtt_debug._INLINE_MAX_SECONDS + 1))
    with pytest.raises(WbCliError) as exc:
        MqttDebugPlugin().dispatch(ctx)
    assert exc.value.code == "MQTT_DEBUG_TOO_LONG"


def test_capture_background_requires_output(fake_config):  # pylint: disable=unused-argument
    ctx = _ctx(_capture_args(seconds=3600, background=True, output=None))
    with pytest.raises(WbCliError) as exc:
        MqttDebugPlugin().dispatch(ctx)
    assert exc.value.code == "MQTT_DEBUG_OUTPUT_REQUIRED"


def test_capture_background_schedules_job(fake_config, tmp_path):  # pylint: disable=unused-argument
    """Each --topic value is shell-quoted in the generated job command."""
    out = tmp_path / "capture.json"
    ctx = _ctx(
        _capture_args(
            seconds=3600,
            background=True,
            output=str(out),
            topic=["K1", "/devices/wb-mdm3_5/controls/Channel 1 Dimming Level/on"],
            client_id=["wb-rules"],
        )
    )
    ctx.job.run.return_value = {"unit": "wb-cli-job-mqtt-debug-capture-1", "log": "/tmp/foo.log"}
    result = MqttDebugPlugin().dispatch(ctx)
    assert result["unit"] == "wb-cli-job-mqtt-debug-capture-1"
    assert result["output"] == str(out)
    cmd = ctx.job.run.call_args.args[1]
    assert "wb-cli --json mqtt-debug capture --seconds 3600" in cmd
    assert "--topic K1" in cmd
    # Topic with spaces must be single-quoted so the shell sees it as one token.
    assert "'/devices/wb-mdm3_5/controls/Channel 1 Dimming Level/on'" in cmd
    assert "--client-id wb-rules" in cmd
    assert f"--output {out}" in cmd


def test_capture_keep_enabled_skips_restore(monkeypatch, fake_config):
    monkeypatch.setattr(mqtt_debug, "countdown", lambda *a, **kw: None)
    ctx = _ctx(_capture_args(seconds=2, keep_enabled=True))
    ctx.journal.read.return_value = []
    MqttDebugPlugin().dispatch(ctx)
    # We toggled on but --keep-enabled means we don't toggle off → 1 restart, file remains.
    assert ctx.systemd.restart.call_count == 1
    assert fake_config.exists()


def test_capture_invalid_seconds(fake_config):  # pylint: disable=unused-argument
    ctx = _ctx(_capture_args(seconds=0))
    with pytest.raises(WbCliError) as exc:
        MqttDebugPlugin().dispatch(ctx)
    assert exc.value.code == "MQTT_DEBUG_INVALID_SECONDS"
