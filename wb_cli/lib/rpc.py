"""RpcClient — MQTT-RPC calls via the ``mqtt-rpc-client`` helper.

Shells out so that no Python ``mqttrpc`` dependency is required on the
development machine.  A direct ``mqttrpc.client.TMQTTRPCClient`` call is
a future optimisation.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Optional

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.mqtt import LiveSub
from wb_cli.lib.shell import ShellRunner


def _validate_target(target: str) -> tuple:
    parts = target.split("/", 2)
    if len(parts) != 3 or not all(parts):
        raise WbCliError(
            code="RPC_INVALID_TARGET",
            message=f"RPC target must be 'driver/service/method', got '{target}'",
            details={"target": target},
            exit_code=ExitCode.DOMAIN,
        )
    return tuple(parts)


class RpcClient:  # pylint: disable=too-few-public-methods
    """Issue MQTT-RPC calls and return parsed responses."""

    def __init__(self, shell: ShellRunner) -> None:
        self._sh = shell

    def call(
        self,
        target: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        timeout: float = 5.0,
    ) -> Dict[str, Any]:
        """Call *target* (``driver/service/method``) with *params*.

        Returns the result dict or raises on RPC error / timeout.
        """
        driver, service, method = _validate_target(target)
        cmd = [
            "mqtt-rpc-client",
            "-d",
            driver,
            "-s",
            service,
            "-m",
            method,
            "-t",
            str(int(timeout)),
        ]
        if params:
            try:
                cmd.extend(["-a", json.dumps(params)])
            except (TypeError, ValueError) as exc:
                raise WbCliError(
                    code="RPC_INVALID_PARAMS",
                    message="RPC params must be valid JSON",
                    details={"params": str(params)},
                    exit_code=ExitCode.DOMAIN,
                ) from exc

        try:
            rc, stdout, stderr = self._sh.run(cmd, timeout=timeout + 2)
        except WbCliError as exc:
            if exc.code == "SHELL_TIMEOUT":
                raise WbCliError(
                    code="RPC_NO_REPLY",
                    message=f"RPC call to '{target}' timed out after {timeout}s",
                    details={"target": target, "timeout_seconds": timeout},
                    exit_code=ExitCode.DOMAIN,
                ) from exc
            raise

        if rc != 0:
            # mqtt-rpc-client writes server-side errors to stdout ("Error: ..."),
            # not stderr; fall back to stdout if stderr is empty so the user
            # actually sees what the RPC server said.
            server_msg = stderr.strip() or stdout.strip()
            raise WbCliError(
                code="RPC_ERROR_RESPONSE",
                message=f"RPC call to '{target}' failed: {server_msg}",
                hint=_hint_for_server_error(driver, server_msg),
                details={
                    "target": target,
                    "returncode": rc,
                    "stderr": stderr.strip(),
                    "stdout": stdout.strip(),
                },
                exit_code=ExitCode.DOMAIN,
            )

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise WbCliError(
                code="RPC_ERROR_RESPONSE",
                message=f"RPC response is not valid JSON: {stdout[:200]}",
                details={"target": target, "stdout": stdout.strip()},
                exit_code=ExitCode.DOMAIN,
            ) from exc

    def call_watch(  # pylint: disable=too-many-arguments
        self,
        target: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        state_topic: str,
        skip_retained: bool = True,
        settle_s: float = 0.5,
        timeout: float = 60.0,
        on_state: Callable[[str], bool],
        on_tick: Optional[Callable[[], bool]] = None,
        rpc_timeout: float = 5.0,
    ) -> None:
        """Call *target* RPC then stream *state_topic* until *on_state* returns True or *timeout* elapses.

        Opens a ``LiveSub`` on *state_topic* before calling the RPC so no messages are missed.
        *on_state(payload)* is called for every message; return True to stop.
        *on_tick()* (optional) is called after each poll interval; return True to stop early.
        """
        with LiveSub(state_topic, skip_retained=skip_retained) as sub:
            time.sleep(settle_s)
            self.call(target, params, timeout=rpc_timeout)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for payload in sub.poll(0.1):
                    if on_state(payload):
                        return
                if on_tick is not None and on_tick():
                    return


# Map server-side import-time failures to a "your daemon is outdated" hint.
# The pattern we hit in the wild: wb-device-manager 1.14.1 on Python 3.9 fails
# to import HeaderWriteError from email.errors (added in 3.12). Newer
# versions of the daemon don't reach for that symbol. Every RPC call against
# a stale daemon surfaces the same ImportError, so a generic match is enough.
_DAEMON_PACKAGE = {
    "wb-device-manager": "wb-device-manager",
    "wbrules": "wb-rules",
    "wb-mqtt-serial": "wb-mqtt-serial",
    "confed": "wb-mqtt-confed",
}


def _hint_for_server_error(driver: str, server_msg: str) -> Optional[str]:
    if "ImportError" not in server_msg and "cannot import name" not in server_msg:
        return None
    pkg = _DAEMON_PACKAGE.get(driver, driver)
    return (
        f"{pkg} on this controller looks too old for the system Python. "
        f"Upgrade it: `apt-get update && apt-get install -y {pkg}`."
    )
