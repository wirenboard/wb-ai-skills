"""MqttClient — thin wrapper over mosquitto_sub / mosquitto_pub.

Uses TAB-separated output format (``-F '%t\\t%p'``); never ``-v``,
because control names may contain spaces.

``subscribe`` streams retained messages and exits once the broker has been
idle for a short window (see ``_IDLE_WINDOW_S``).  We can't rely on
``mosquitto_sub -W <timeout>`` alone: that keeps the connection open for
the full timeout even after every retained value has already arrived,
making ``devices list`` feel "stuck" for 5 seconds when in fact the data
landed in the first 50 ms.
"""

from __future__ import annotations

import select
import subprocess
import time
from typing import List, Tuple

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.shell import ShellRunner

_IDLE_WINDOW_S = 0.3
_POLL_INTERVAL_S = 0.05


class MqttClient:
    """Publish and subscribe via mosquitto CLI tools."""

    def __init__(self, shell: ShellRunner) -> None:
        self._sh = shell

    def subscribe(
        self,
        topic: str,
        *,
        timeout: float = 5.0,
        retained_only: bool = True,  # pylint: disable=unused-argument
    ) -> List[Tuple[str, str]]:
        """Subscribe and collect retained messages.

        Returns a list of ``(topic, payload)`` tuples.  Exits once retained
        delivery looks done (idle window after the first message) or *timeout*
        seconds have passed, whichever comes first.
        """
        try:
            proc = subprocess.Popen(  # pylint: disable=consider-using-with
                ["mosquitto_sub", "-F", "%t\t%p", "-t", topic],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise WbCliError(
                code="MQTT_BROKER_DOWN",
                message="mosquitto_sub not found; is mosquitto-clients installed?",
                exit_code=ExitCode.ENVIRONMENT,
            ) from exc

        results: List[Tuple[str, str]] = []
        try:
            results = _drain_retained(proc, topic, timeout)
        finally:
            proc.terminate()
            try:
                _, stderr = proc.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                _, stderr = proc.communicate()

        rc = proc.returncode
        # Negative rc = killed by signal (our terminate). Anything other than
        # a successful exit or our own kill, with empty output, means the
        # broker rejected us.
        if not results and rc not in (0, None) and rc > 0:
            raise WbCliError(
                code="MQTT_BROKER_DOWN",
                message=f"mosquitto_sub failed (rc={rc}): {(stderr or '').strip()}",
                details={"topic": topic, "returncode": rc},
                exit_code=ExitCode.ENVIRONMENT,
            )
        return results

    def publish(
        self,
        topic: str,
        payload: str,
        *,
        retain: bool = False,
        timeout: float = 5.0,
    ) -> None:
        """Publish a single message."""
        cmd = ["mosquitto_pub", "-t", topic, "-m", payload]
        if retain:
            cmd.append("-r")
        try:
            rc, _, stderr = self._sh.run(cmd, timeout=timeout)
        except WbCliError as exc:
            if exc.code == "FS_NOT_FOUND":
                raise WbCliError(
                    code="MQTT_BROKER_DOWN",
                    message="mosquitto_pub not found; is mosquitto-clients installed?",
                    exit_code=ExitCode.ENVIRONMENT,
                ) from exc
            raise
        if rc != 0:
            raise WbCliError(
                code="MQTT_PUBLISH_FAILED",
                message=f"mosquitto_pub failed: {stderr.strip()}",
                details={"topic": topic, "returncode": rc},
                exit_code=ExitCode.ENVIRONMENT,
            )


def _drain_retained(proc, topic: str, timeout: float) -> List[Tuple[str, str]]:
    """Read messages until the broker is idle for ``_IDLE_WINDOW_S`` or we hit *timeout*.

    Raises ``MQTT_TIMEOUT`` if nothing at all arrived within *timeout* seconds.
    """
    results: List[Tuple[str, str]] = []
    deadline = time.monotonic() + timeout
    last_msg_at: float = 0.0
    while time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], _POLL_INTERVAL_S)
        if ready:
            line = proc.stdout.readline()
            if not line:
                break
            if "\t" in line:
                t, _, p = line.rstrip("\n").partition("\t")
                results.append((t, p))
                last_msg_at = time.monotonic()
        elif results and (time.monotonic() - last_msg_at) > _IDLE_WINDOW_S:
            return results
    if not results:
        raise WbCliError(
            code="MQTT_TIMEOUT",
            message=f"No messages on '{topic}' within {timeout}s",
            details={"topic": topic, "timeout_seconds": timeout},
            exit_code=ExitCode.DOMAIN,
        )
    return results
