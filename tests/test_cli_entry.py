"""Top-level CLI behaviour: argv parsing, output-mode resolution, help screens."""

from __future__ import annotations

import pytest
from wb_cli.cli import _pop_global_flags, _resolve_output_mode, main


def test_no_args_prints_help(capsys):
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "usage: wb-cli" in captured.out
    assert "<command>" in captured.out


def test_help_flag_prints_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "usage: wb-cli" in captured.out


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "wb-cli " in captured.out


# --- global flag parsing ---


def test_pop_global_flags_extracts_json_anywhere():
    assert _pop_global_flags(["--json", "info"]) == (["info"], "json")
    assert _pop_global_flags(["info", "--json"]) == (["info"], "json")
    assert _pop_global_flags(["info"]) == (["info"], None)


def test_pop_global_flags_extracts_human():
    assert _pop_global_flags(["--human", "info"]) == (["info"], "human")


# --- output mode resolution ---


def test_output_mode_flag_wins_over_env(monkeypatch):
    monkeypatch.setenv("WB_CLI_OUTPUT", "human")
    assert _resolve_output_mode("json") == "json"


def test_output_mode_env_overrides_tty_heuristic(monkeypatch):
    monkeypatch.setenv("WB_CLI_OUTPUT", "json")
    # Pretend stdout is a TTY; env should still force json.
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert _resolve_output_mode(None) == "json"


def test_output_mode_defaults_to_json_for_non_tty(monkeypatch):
    monkeypatch.delenv("WB_CLI_OUTPUT", raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert _resolve_output_mode(None) == "json"


def test_output_mode_defaults_to_human_for_tty(monkeypatch):
    monkeypatch.delenv("WB_CLI_OUTPUT", raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert _resolve_output_mode(None) == "human"


def test_output_mode_ignores_unknown_env_value(monkeypatch):
    monkeypatch.setenv("WB_CLI_OUTPUT", "garbage")
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert _resolve_output_mode(None) == "json"
