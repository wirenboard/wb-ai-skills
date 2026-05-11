"""Tests for ``wb-cli info`` against fixture data."""

# pylint: disable=protected-access

from __future__ import annotations

import argparse
from pathlib import Path

from wb_cli.commands.info import InfoPlugin
from wb_cli.context import CliContext
from wb_cli.lib.controller import ControllerInfo


def _ctx(controller_root: Path) -> CliContext:  # pylint: disable=protected-access
    ctx = CliContext(argparse.Namespace(quiet=False))
    ctx._controller = ControllerInfo(root=controller_root)
    return ctx


def test_info_returns_serial(controller_root: Path):
    result = InfoPlugin().dispatch(_ctx(controller_root))
    assert result["serial_number"] == "A25NDEMJ"


def test_info_returns_release(controller_root: Path):
    result = InfoPlugin().dispatch(_ctx(controller_root))
    assert result["release_name"] == "wb-2602"
    assert result["target"] == "wb7/bullseye"


def test_info_returns_device_tree(controller_root: Path):
    result = InfoPlugin().dispatch(_ctx(controller_root))
    assert result["device_tree"]["board-revision"] == "7.3.1"
