"""Tests for wb_cli.output — emit_data / emit_error envelopes."""

from __future__ import annotations

import io
import json

import pytest
from wb_cli.errors import ExitCode, WbCliError
from wb_cli.output import emit_data, emit_error


def _capture_json(func, *args, **kwargs) -> dict:
    buf = io.StringIO()
    func(*args, stream=buf, **kwargs)
    return json.loads(buf.getvalue())


def test_emit_data_wraps_in_data_key():
    result = _capture_json(emit_data, {"serial_number": "A25NDEMJ"})
    assert "data" in result
    assert result["data"]["serial_number"] == "A25NDEMJ"


def test_emit_data_empty_dict():
    result = _capture_json(emit_data, {})
    assert result == {"data": {}}


def test_emit_data_rejects_non_dict():
    with pytest.raises(TypeError, match="data must be a dict"):
        _capture_json(emit_data, [1, 2, 3])


def test_emit_error_wraps_in_error_key():
    err = WbCliError(
        code="MQTT_BROKER_DOWN",
        message="Broker not reachable",
        exit_code=ExitCode.ENVIRONMENT,
    )
    result = _capture_json(emit_error, err)
    assert "error" in result
    assert result["error"]["code"] == "MQTT_BROKER_DOWN"


def test_emit_data_json_is_valid():
    buf = io.StringIO()
    emit_data({"key": "value"}, stream=buf)
    raw = buf.getvalue()
    # Must end with newline
    assert raw.endswith("\n")
    parsed = json.loads(raw)
    assert parsed["data"]["key"] == "value"
