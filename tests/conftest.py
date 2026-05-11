"""Shared pytest fixtures for wb-cli tests."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from wb_cli.errors import WbCliError


@pytest.fixture()
def shell_returning():
    """Factory: build a ShellRunner mock whose .run() returns (rc, stdout, stderr)."""

    def _make(rc: int, stdout: str = "", stderr: str = "") -> MagicMock:
        shell = MagicMock()
        shell.run.return_value = (rc, stdout, stderr)
        return shell

    return _make


@pytest.fixture()
def shell_raising():
    """Factory: build a ShellRunner mock whose .run() raises WbCliError(code)."""

    def _make(code: str) -> MagicMock:
        shell = MagicMock()
        shell.run.side_effect = WbCliError(code=code, message="x", exit_code=3)
        return shell

    return _make


# Root of captured controller fixtures
_FIXTURES = Path(__file__).parent / "fixtures" / "controller"


@pytest.fixture()
def controller_root(tmp_path: Path) -> Path:
    """Build a fake sysroot from captured fixture files.

    Maps fixture files to the real filesystem layout that
    :class:`wb_cli.lib.controller.ControllerInfo` expects::

        etc/wb-release
        etc/wb-fw-version
        etc/hostname
        var/lib/wirenboard/short_sn.conf
        proc/uptime
        proc/device-tree/wirenboard/
    """
    _copy(_FIXTURES / "identity" / "wb-release.txt", tmp_path / "etc" / "wb-release")
    _copy(_FIXTURES / "identity" / "wb-fw-version.txt", tmp_path / "etc" / "wb-fw-version")
    _copy(_FIXTURES / "hostname.txt", tmp_path / "etc" / "hostname")
    _copy(_FIXTURES / "identity" / "short_sn.conf", tmp_path / "var" / "lib" / "wirenboard" / "short_sn.conf")
    _copy(_FIXTURES / "system" / "uptime.txt", tmp_path / "proc" / "uptime")

    dt_src = _FIXTURES / "identity" / "device-tree"
    dt_dst = tmp_path / "proc" / "device-tree" / "wirenboard"
    if dt_src.is_dir():
        shutil.copytree(dt_src, dt_dst)

    return tmp_path


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
