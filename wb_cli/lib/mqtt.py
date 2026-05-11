"""MqttClient — thin wrapper over mosquitto_sub / mosquitto_pub.

Uses TAB-separated output format (``-F '%t\\t%p'``); never ``-v``,
because control names may contain spaces.
"""

from __future__ import annotations

from typing import List, Tuple

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.shell import ShellRunner


class MqttClient:
    """Publish and subscribe via mosquitto CLI tools."""

    def __init__(self, shell: ShellRunner) -> None:
        self._sh = shell

    def subscribe(
        self,
        topic: str,
        *,
        timeout: float = 5.0,
        retained_only: bool = True,
    ) -> List[Tuple[str, str]]:
        """Subscribe and collect messages.

        Returns list of (topic, payload) tuples.  With *retained_only*
        the client exits after receiving all retained messages (``-E``).
        """
        wait_seconds = max(1, int(timeout))
        cmd = [
            "mosquitto_sub",
            "-F",
            "%t\t%p",
            "-W",
            str(wait_seconds),
            "-t",
            topic,
        ]
        if retained_only:
            cmd.append("--retained-only")
        try:
            rc, stdout, stderr = self._sh.run(cmd, timeout=wait_seconds + 2)
        except WbCliError as exc:
            if exc.code == "TIMEOUT":
                raise WbCliError(
                    code="MQTT_TIMEOUT",
                    message=f"No messages on '{topic}' within {timeout}s",
                    details={"topic": topic, "timeout_seconds": timeout},
                    exit_code=ExitCode.DOMAIN,
                ) from exc
            if exc.code == "FS_NOT_FOUND":
                raise WbCliError(
                    code="MQTT_BROKER_DOWN",
                    message="mosquitto_sub not found; is mosquitto-clients installed?",
                    exit_code=ExitCode.ENVIRONMENT,
                ) from exc
            raise

        # mosquitto_sub returns 27 when -W timeout fires with no broker errors;
        # treat as "no retained messages here", not as a broker fault.
        if rc not in (0, 27) and not stdout.strip():
            raise WbCliError(
                code="MQTT_BROKER_DOWN",
                message=f"mosquitto_sub failed (rc={rc}): {stderr.strip()}",
                details={"topic": topic, "returncode": rc},
                exit_code=ExitCode.ENVIRONMENT,
            )

        results: List[Tuple[str, str]] = []
        for line in stdout.splitlines():
            if "\t" not in line:
                continue
            t, _, p = line.partition("\t")
            results.append((t, p))
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
