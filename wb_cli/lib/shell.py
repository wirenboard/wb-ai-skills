"""ShellRunner — subprocess fallback for commands without a dedicated handle."""

from __future__ import annotations

import subprocess
from typing import Optional, Tuple

from wb_cli.errors import ExitCode, WbCliError


class ShellRunner:  # pylint: disable=too-few-public-methods
    """Run shell commands and return (returncode, stdout, stderr)."""

    def run(
        self,
        cmd: list[str],
        *,
        timeout: Optional[float] = None,
        check: bool = False,
        stdin_data: Optional[str] = None,
    ) -> Tuple[int, str, str]:
        """Execute *cmd* as a subprocess.

        Returns (returncode, stdout, stderr).  When *check* is True,
        raises :class:`WbCliError` on non-zero exit.
        """
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                input=stdin_data,
                check=False,
            )
        except FileNotFoundError as exc:
            raise WbCliError(
                code="FS_NOT_FOUND",
                message=f"Command not found: {cmd[0]}",
                details={"command": cmd[0]},
                exit_code=ExitCode.ENVIRONMENT,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise WbCliError(
                code="SHELL_TIMEOUT",
                message=f"Command timed out after {timeout}s: {' '.join(cmd)}",
                details={"command": cmd, "timeout_seconds": timeout},
                exit_code=ExitCode.ENVIRONMENT,
            ) from exc

        if check and proc.returncode != 0:
            raise WbCliError(
                code="SHELL_COMMAND_FAILED",
                message=f"Command failed (exit {proc.returncode}): {' '.join(cmd)}",
                details={
                    "command": cmd,
                    "returncode": proc.returncode,
                    "stderr": proc.stderr.strip(),
                },
                exit_code=ExitCode.ENVIRONMENT,
            )
        return proc.returncode, proc.stdout, proc.stderr
