"""JournalReader — journalctl wrapper for structured log access."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.shell import ShellRunner


class JournalReader:  # pylint: disable=too-few-public-methods
    """Read systemd journal entries via journalctl."""

    def __init__(self, shell: ShellRunner) -> None:
        self._sh = shell

    def read(  # pylint: disable=too-many-arguments
        self,
        *,
        unit: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        lines: Optional[int] = None,
        priority: Optional[str] = None,
        timeout: float = 10.0,
    ) -> List[Dict[str, Any]]:
        """Read journal entries as a list of dicts.

        Uses ``--output=json`` for structured output.
        """
        cmd = ["journalctl", "--no-pager", "--output=json"]

        if unit:
            cmd.extend(["-u", unit])
        if since:
            cmd.extend(["--since", since])
        if until:
            cmd.extend(["--until", until])
        if lines is not None:
            cmd.extend(["-n", str(lines)])
        if priority:
            cmd.extend(["-p", priority])

        try:
            rc, stdout, stderr = self._sh.run(cmd, timeout=timeout)
        except WbCliError as exc:
            if exc.code == "FS_NOT_FOUND":
                raise WbCliError(
                    code="JOURNAL_UNAVAILABLE",
                    message="journalctl not available",
                    exit_code=ExitCode.ENVIRONMENT,
                ) from exc
            raise

        if rc != 0 and "Invalid time" in stderr:
            raise WbCliError(
                code="JOURNAL_INVALID_TIME",
                message=f"Invalid time specification: {stderr.strip()}",
                details={"since": since, "until": until},
                exit_code=ExitCode.DOMAIN,
            )

        return _parse_journal_json(stdout)


def _parse_journal_json(text: str) -> List[Dict[str, Any]]:
    """Parse NDJSON output from journalctl --output=json."""
    entries: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
