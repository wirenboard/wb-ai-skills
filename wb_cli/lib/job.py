"""JobManager — managed background tasks via systemd-run.

Jobs live under ``/mnt/data/ai/wb-cli/jobs/<unit>.{sh,log,label,started}``;
``run`` wraps ``systemd-run --collect`` and garbage-collects entries older
than 24 hours.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.shell import ShellRunner

_JOBS_DIR = Path("/mnt/data/ai/wb-cli/jobs")
_GC_AGE_SECONDS = 86400  # 24 hours


class JobManager:
    """Create, monitor, and manage background jobs."""

    def __init__(self, shell: ShellRunner, jobs_dir: Path = _JOBS_DIR) -> None:
        self._sh = shell
        self._dir = jobs_dir

    def run(
        self,
        label: str,
        command: str,
        *,
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        """Start a background job. Returns job metadata."""
        self._gc()
        self._dir.mkdir(parents=True, exist_ok=True)

        unit = f"wb-cli-job-{label}-{int(time.time())}"
        log_path = self._dir / f"{unit}.log"
        script_path = self._dir / f"{unit}.sh"
        label_path = self._dir / f"{unit}.label"
        started_path = self._dir / f"{unit}.started"

        script_path.write_text(command, encoding="utf-8")
        label_path.write_text(label, encoding="utf-8")
        started_path.write_text(
            time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            encoding="utf-8",
        )

        rc, _, stderr = self._sh.run(
            [
                "systemd-run",
                "--collect",
                f"--unit={unit}",
                f"--property=StandardOutput=append:{log_path}",
                f"--property=StandardError=append:{log_path}",
                "/bin/bash",
                str(script_path),
            ],
            timeout=timeout,
        )
        if rc != 0:
            raise WbCliError(
                code="JOB_ALREADY_RUNNING",
                message=f"Failed to start job '{label}': {stderr.strip()}",
                details={"label": label, "unit": unit},
                exit_code=ExitCode.DOMAIN,
            )
        return {"unit": unit, "label": label, "log": str(log_path)}

    def status(self, unit: str, *, timeout: float = 5.0) -> Dict[str, Any]:
        """Return job status."""
        rc, stdout, _ = self._sh.run(
            ["systemctl", "is-active", unit],
            timeout=timeout,
        )
        state = stdout.strip() if rc == 0 else "inactive"
        log_path = self._dir / f"{unit}.log"
        label_path = self._dir / f"{unit}.label"
        return {
            "unit": unit,
            "label": _read_file(label_path),
            "state": state,
            "log_path": str(log_path),
        }

    def tail(
        self,
        unit: str,
        lines: int = 50,
        *,
        timeout: float = 5.0,
    ) -> str:
        """Return last N lines of job log."""
        log_path = self._dir / f"{unit}.log"
        if not log_path.exists():
            raise WbCliError(
                code="JOB_NOT_FOUND",
                message=f"No log for job '{unit}'",
                details={"unit": unit},
                exit_code=ExitCode.DOMAIN,
            )
        _, stdout, _ = self._sh.run(
            ["tail", f"-n{lines}", str(log_path)],
            timeout=timeout,
        )
        return stdout

    def cancel(self, unit: str, *, timeout: float = 10.0) -> None:
        """Stop a running job."""
        rc, _, stderr = self._sh.run(
            ["systemctl", "stop", unit],
            timeout=timeout,
        )
        if rc != 0:
            raise WbCliError(
                code="JOB_NOT_FOUND",
                message=f"Cannot cancel job '{unit}': {stderr.strip()}",
                details={"unit": unit},
                exit_code=ExitCode.DOMAIN,
            )

    def wait(
        self,
        unit: str,
        *,
        timeout: float = 300.0,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """Poll until job finishes or timeout expires."""
        from wb_cli.lib.progress import Spinner  # pylint: disable=import-outside-toplevel

        deadline = time.time() + timeout
        with Spinner(f"waiting for {unit}"):
            while time.time() < deadline:
                rc, _, _ = self._sh.run(
                    ["systemctl", "is-active", "--quiet", unit],
                    timeout=5.0,
                )
                if rc != 0:
                    return self.status(unit)
                time.sleep(poll_interval)
        raise WbCliError(
            code="JOB_WAIT_TIMEOUT",
            message=f"Job '{unit}' still running after {timeout}s",
            details={"unit": unit, "timeout_seconds": timeout},
            exit_code=ExitCode.DOMAIN,
        )

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all known jobs."""
        if not self._dir.exists():
            return []
        jobs: List[Dict[str, Any]] = []
        for label_file in sorted(self._dir.glob("*.label")):
            unit = label_file.stem
            label = _read_file(label_file)
            started = _read_file(self._dir / f"{unit}.started")
            jobs.append(
                {
                    "unit": unit,
                    "label": label,
                    "started": started,
                }
            )
        return jobs

    def _gc(self) -> None:
        """Remove job files older than 24 hours."""
        if not self._dir.exists():
            return
        now = time.time()
        for label_file in self._dir.glob("*.label"):
            if now - label_file.stat().st_mtime > _GC_AGE_SECONDS:
                unit = label_file.stem
                for suffix in (".sh", ".log", ".label", ".started"):
                    path = self._dir / f"{unit}{suffix}"
                    if path.exists():
                        path.unlink()


def _read_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
