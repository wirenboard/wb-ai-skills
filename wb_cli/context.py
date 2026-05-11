"""CliContext — the object passed to every plugin's ``dispatch``."""

from __future__ import annotations

import argparse
import sys
from typing import IO

from wb_cli.lib.controller import ControllerInfo
from wb_cli.lib.job import JobManager
from wb_cli.lib.journal import JournalReader
from wb_cli.lib.mqtt import MqttClient
from wb_cli.lib.rpc import RpcClient
from wb_cli.lib.shell import ShellRunner
from wb_cli.lib.systemd import SystemdManager


class Logger:
    """Minimal logger writing to stderr, honoring -q/--quiet."""

    def __init__(self, *, quiet: bool = False, stream: IO[str] = sys.stderr) -> None:
        self.quiet = quiet
        self.stream = stream

    def info(self, message: str) -> None:
        if not self.quiet:
            print(f"info: {message}", file=self.stream)

    def warning(self, message: str) -> None:
        print(f"warning: {message}", file=self.stream)


class CliContext:  # pylint: disable=too-many-instance-attributes
    """Object passed to every plugin's ``dispatch``.

    Handles are created lazily on first access — ``wb-cli info``
    does not instantiate MqttClient or RpcClient.
    """

    def __init__(self, args: argparse.Namespace, *, quiet: bool = False) -> None:
        self.args = args
        self.log = Logger(quiet=quiet)
        self._shell: ShellRunner | None = None
        self._controller: ControllerInfo | None = None
        self._mqtt: MqttClient | None = None
        self._rpc: RpcClient | None = None
        self._systemd: SystemdManager | None = None
        self._journal: JournalReader | None = None
        self._job: JobManager | None = None

    @property
    def shell(self) -> ShellRunner:
        if self._shell is None:
            self._shell = ShellRunner()
        return self._shell

    @property
    def controller(self) -> ControllerInfo:
        if self._controller is None:
            self._controller = ControllerInfo()
        return self._controller

    @property
    def mqtt(self) -> MqttClient:
        if self._mqtt is None:
            self._mqtt = MqttClient(self.shell)
        return self._mqtt

    @property
    def rpc(self) -> RpcClient:
        if self._rpc is None:
            self._rpc = RpcClient(self.shell)
        return self._rpc

    @property
    def systemd(self) -> SystemdManager:
        if self._systemd is None:
            self._systemd = SystemdManager(self.shell)
        return self._systemd

    @property
    def journal(self) -> JournalReader:
        if self._journal is None:
            self._journal = JournalReader(self.shell)
        return self._journal

    @property
    def job(self) -> JobManager:
        if self._job is None:
            self._job = JobManager(self.shell)
        return self._job
