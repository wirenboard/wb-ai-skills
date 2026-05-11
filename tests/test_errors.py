"""Tests for wb_cli.errors — ExitCode and WbCliError envelope."""

from __future__ import annotations

from wb_cli.errors import ExitCode, WbCliError


def test_exit_code_values():
    assert ExitCode.SUCCESS == 0
    assert ExitCode.DOMAIN == 1
    assert ExitCode.USAGE == 2
    assert ExitCode.ENVIRONMENT == 3
    assert ExitCode.INTERRUPTED == 130


def test_error_to_envelope_minimal():
    err = WbCliError(code="MQTT_BROKER_DOWN", message="Broker not reachable")
    envelope = err.to_envelope()
    assert "error" in envelope
    assert envelope["error"]["code"] == "MQTT_BROKER_DOWN"
    assert envelope["error"]["message"] == "Broker not reachable"
    assert envelope["error"]["details"] == {}
    assert "hint" not in envelope["error"]


def test_error_to_envelope_with_hint_and_details():
    err = WbCliError(
        code="RULES_NOT_FOUND",
        message="Rule 'foo' not found",
        hint="Run: wb-cli rules list",
        details={"name": "foo"},
        exit_code=ExitCode.DOMAIN,
    )
    envelope = err.to_envelope()
    assert envelope["error"]["hint"] == "Run: wb-cli rules list"
    assert envelope["error"]["details"] == {"name": "foo"}


def test_error_exit_code_default():
    err = WbCliError(code="X", message="x")
    assert err.exit_code == ExitCode.DOMAIN


def test_error_exit_code_custom():
    err = WbCliError(code="X", message="x", exit_code=ExitCode.ENVIRONMENT)
    assert err.exit_code == ExitCode.ENVIRONMENT


def test_error_is_exception():
    err = WbCliError(code="X", message="something broke")
    assert isinstance(err, Exception)
    assert str(err) == "something broke"
