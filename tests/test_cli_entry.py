"""Top-level CLI behaviour: no-args prints help, --help and --version work."""

from __future__ import annotations

import pytest
from wb_cli.cli import main


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
