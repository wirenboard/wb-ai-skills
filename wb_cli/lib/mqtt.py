"""MqttClient — thin wrapper over mosquitto_sub / mosquitto_pub.

Uses TAB-separated output format (``-F '%t\\t%p'``); never ``-v``,
because control names may contain spaces.

``subscribe`` streams retained messages and exits once the broker has been
idle for a short window (see ``_IDLE_WINDOW_S``).  We can't rely on
``mosquitto_sub -W <timeout>`` alone: that keeps the connection open for
the full timeout even after every retained value has already arrived,
making ``devices list`` feel "stuck" for 5 seconds when in fact the data
landed in the first 50 ms.

Two buffering quirks to dodge:
  * mosquitto_sub full-buffers stdout under a pipe — we run it through
    ``stdbuf -oL`` so every retained message flushes immediately.
  * Python's ``proc.stdout`` wraps the file descriptor in a BufferedReader,
    so once ``readline`` slurps the whole pipe into its private buffer,
    ``select(fileno)`` says "nothing here" and we miss subsequent lines.
    We read the raw fd ourselves and split on ``\\n``.
"""

from __future__ import annotations

import errno
import os
import select
import subprocess
import time
from typing import List, Optional, Tuple

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.shell import ShellRunner

_IDLE_WINDOW_S = 0.3
_POLL_INTERVAL_S = 0.05
_READ_CHUNK = 4096


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
        # Force mosquitto_sub's stdout to be line-buffered. Under a pipe it
        # would otherwise full-buffer, batching multiple retained messages
        # into one flush — that breaks our idle-window heuristic and we
        # silently miss meta-keys for short replies.
        cmd = [
            "stdbuf",
            "-oL",
            "mosquitto_sub",
            "-F",
            "%t\t%p",
            "-t",
            topic,
        ]
        try:
            proc = subprocess.Popen(  # pylint: disable=consider-using-with
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # Bytes mode — we read the raw fd via os.read() and split on
                # newlines ourselves so Python's BufferedReader doesn't gobble
                # multiple retained messages into its private buffer.
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
        stderr_text = (
            stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
        ) or ""
        # Negative rc = killed by signal (our terminate). Anything other than
        # a successful exit or our own kill, with empty output, means the
        # broker rejected us.
        if not results and rc not in (0, None) and rc > 0:
            raise WbCliError(
                code="MQTT_BROKER_DOWN",
                message=f"mosquitto_sub failed (rc={rc}): {stderr_text.strip()}",
                details={"topic": topic, "returncode": rc},
                exit_code=ExitCode.ENVIRONMENT,
            )
        return results

    def subscribe_live(
        self,
        topic: str,
        *,
        count: Optional[int] = None,
        timeout: float = 5.0,
    ) -> List[Tuple[str, str]]:
        """Subscribe and collect messages — both retained and live.

        Unlike ``subscribe``, does not use an idle-window heuristic.
        Waits until *count* messages arrive or *timeout* seconds elapse.
        """
        cmd = [
            "stdbuf",
            "-oL",
            "mosquitto_sub",
            "-F",
            "%t\t%p",
            "-t",
            topic,
            "-W",
            str(max(1, int(timeout + 0.5))),
        ]
        if count is not None:
            cmd += ["-C", str(count)]
        try:
            proc = subprocess.Popen(  # pylint: disable=consider-using-with
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise WbCliError(
                code="MQTT_BROKER_DOWN",
                message="mosquitto_sub not found; is mosquitto-clients installed?",
                exit_code=ExitCode.ENVIRONMENT,
            ) from exc

        results: List[Tuple[str, str]] = []
        try:
            stdout, stderr = proc.communicate(timeout=timeout + 2.0)
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                if "\t" in line:
                    t, _, p = line.partition("\t")
                    results.append((t, p))
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate()
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                if "\t" in line:
                    t, _, p = line.partition("\t")
                    results.append((t, p))
            stderr = b""

        rc = proc.returncode
        stderr_text = (stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else "").strip()
        if not results and rc is not None and rc > 0:
            raise WbCliError(
                code="MQTT_BROKER_DOWN",
                message=f"mosquitto_sub failed (rc={rc}): {stderr_text}",
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
    fd = proc.stdout.fileno()
    os.set_blocking(fd, False)
    results: List[Tuple[str, str]] = []
    buf = b""
    deadline = time.monotonic() + timeout
    last_msg_at: float = 0.0
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], _POLL_INTERVAL_S)
        if ready:
            try:
                chunk = os.read(fd, _READ_CHUNK)
            except BlockingIOError:
                chunk = b""
            except OSError as exc:
                if exc.errno == errno.EAGAIN:
                    chunk = b""
                else:
                    raise
            if not chunk and proc.poll() is not None:
                break
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                line_str = line.decode("utf-8", errors="replace")
                if "\t" in line_str:
                    t, _, p = line_str.partition("\t")
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
