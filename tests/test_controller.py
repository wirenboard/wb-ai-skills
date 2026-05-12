"""Tests for wb_cli.lib.controller — ControllerInfo against fixture tree."""

from __future__ import annotations

from pathlib import Path

from wb_cli.lib.controller import ControllerInfo


def test_serial_number(controller_root: Path):
    info = ControllerInfo(root=controller_root)
    assert info.serial_number == "A25NDEMJ"


def test_release_fields(controller_root: Path):
    info = ControllerInfo(root=controller_root)
    assert info.release_name == "wb-2602"
    assert info.suite == "stable"
    assert info.target == "wb7/bullseye"


def test_hostname(controller_root: Path):
    info = ControllerInfo(root=controller_root)
    assert info.hostname == "wirenboard-A25NDEMJ"


def test_uptime(controller_root: Path):
    info = ControllerInfo(root=controller_root)
    assert info.uptime_seconds == 226456.49


def test_device_tree_fields(controller_root: Path):
    info = ControllerInfo(root=controller_root)
    dt = info.device_tree
    assert dt["board-revision"] == "7.3.1"
    assert dt["dram-size"] == "2048"
    assert dt["name"] == "wirenboard"
    assert dt["batch-no"] == "7.3.1B/2GC/2T 636"


def test_to_dict_keys(controller_root: Path):
    info = ControllerInfo(root=controller_root)
    data = info.to_dict()
    expected_keys = {
        "serial_number",
        "release_name",
        "suite",
        "target",
        "hostname",
        "uptime_seconds",
        "device_tree",
    }
    assert set(data.keys()) == expected_keys


def test_missing_files(tmp_path: Path):
    info = ControllerInfo(root=tmp_path)
    assert info.serial_number is None
    assert info.release_name is None
    assert info.hostname is None
    assert info.uptime_seconds is None
    assert not info.device_tree


def test_lazy_loading(controller_root: Path):
    info = ControllerInfo(root=controller_root)
    assert not info._loaded  # pylint: disable=protected-access
    _ = info.serial_number
    assert info._loaded  # pylint: disable=protected-access
