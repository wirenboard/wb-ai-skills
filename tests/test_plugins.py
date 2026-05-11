"""Tests for ``wb-cli plugins``."""

from __future__ import annotations

import argparse

import pytest
from wb_cli import __version__
from wb_cli.commands.plugins import PluginsPlugin
from wb_cli.context import CliContext
from wb_cli.errors import WbCliError


def _ctx(name=None):
    return CliContext(argparse.Namespace(name=name, quiet=False))


def test_plugins_list_all():
    result = PluginsPlugin().dispatch(_ctx())
    assert result["wb_cli_version"] == __version__
    assert result["count"] > 0
    assert isinstance(result["plugins"], list)


def test_plugins_detail_found():
    result = PluginsPlugin().dispatch(_ctx(name="info"))
    assert result["name"] == "info"
    assert "module" in result


def test_plugins_detail_not_found():
    with pytest.raises(WbCliError, match="No plugin named 'nonexistent'"):
        PluginsPlugin().dispatch(_ctx(name="nonexistent"))
