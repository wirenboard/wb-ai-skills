"""SystemdManager — systemctl / systemd-run wrapper."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.shell import ShellRunner


class SystemdManager:
    """Interact with systemd units via systemctl."""

    def __init__(self, shell: ShellRunner) -> None:
        self._sh = shell

    def status(self, unit: str, *, timeout: float = 10.0) -> Dict[str, Any]:
        """Return parsed ``systemctl show`` output for *unit*."""
        _, stdout, _ = self._sh.run(
            ["systemctl", "show", "--no-pager", unit],
            timeout=timeout,
        )
        result = _parse_show(stdout)
        if result.get("LoadState") == "not-found":
            raise WbCliError(
                code="SYSTEMD_UNIT_NOT_FOUND",
                message=f"Unit '{unit}' not found",
                details={"unit": unit},
                exit_code=ExitCode.DOMAIN,
            )
        return result

    def start(self, unit: str, *, timeout: float = 30.0) -> None:
        self._action("start", unit, timeout=timeout)

    def stop(self, unit: str, *, timeout: float = 30.0) -> None:
        self._action("stop", unit, timeout=timeout)

    def restart(self, unit: str, *, timeout: float = 30.0) -> None:
        self._action("restart", unit, timeout=timeout)

    def _action(self, verb: str, unit: str, *, timeout: float) -> None:
        rc, _, stderr = self._sh.run(
            ["systemctl", verb, unit],
            timeout=timeout,
        )
        if rc != 0:
            if "Access denied" in stderr or "Permission denied" in stderr:
                raise WbCliError(
                    code="SYSTEMD_PERMISSION_DENIED",
                    message=f"Permission denied: systemctl {verb} {unit}",
                    details={"unit": unit, "verb": verb},
                    exit_code=ExitCode.ENVIRONMENT,
                )
            raise WbCliError(
                code="SYSTEMD_OPERATION_FAILED",
                message=f"systemctl {verb} {unit} failed: {stderr.strip()}",
                details={"unit": unit, "verb": verb, "returncode": rc},
                exit_code=ExitCode.DOMAIN,
            )

    def list_failed(self, *, timeout: float = 10.0) -> List[Dict[str, str]]:
        """Return list of failed units."""
        _, stdout, _ = self._sh.run(
            [
                "systemctl",
                "list-units",
                "--state=failed",
                "--no-pager",
                "--no-legend",
                "--output=json",
            ],
            timeout=timeout,
        )
        return _parse_units_json(stdout)

    def list_units(
        self,
        state: Optional[str] = None,
        *,
        timeout: float = 10.0,
    ) -> List[Dict[str, str]]:
        """Return list of units, optionally filtered by state."""
        cmd = [
            "systemctl",
            "list-units",
            "--no-pager",
            "--no-legend",
            "--output=json",
        ]
        if state:
            cmd.append(f"--state={state}")
        _, stdout, _ = self._sh.run(cmd, timeout=timeout)
        return _parse_units_json(stdout)

    def wait(
        self,
        unit: str,
        state: str = "active",
        *,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> bool:
        """Poll until *unit* reaches *state* or timeout expires."""
        import time  # pylint: disable=import-outside-toplevel

        deadline = time.time() + timeout
        while time.time() < deadline:
            rc, _, _ = self._sh.run(
                ["systemctl", "is-active", "--quiet", unit],
                timeout=5.0,
            )
            reached = (rc == 0) if state == "active" else (rc != 0)
            if reached:
                return True
            time.sleep(poll_interval)
        raise WbCliError(
            code="SYSTEMD_WAIT_TIMEOUT",
            message=f"Unit '{unit}' did not reach state '{state}'",
            details={"unit": unit, "state": state},
            exit_code=ExitCode.DOMAIN,
        )


def _parse_show(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        result[key] = val
    return result


def _parse_units_json(text: str) -> List[Dict[str, str]]:
    text = text.strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return []
