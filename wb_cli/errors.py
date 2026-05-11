"""Error envelope and exit codes for wb-cli."""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Optional


class ExitCode(IntEnum):
    """Process exit codes used across wb-cli."""

    SUCCESS = 0
    DOMAIN = 1  # operation finished but condition unmet (fixable via args)
    USAGE = 2  # argparse-level error
    ENVIRONMENT = 3  # external system unavailable / unfixable from args
    INTERRUPTED = 130  # SIGINT


class WbCliError(Exception):  # pylint: disable=too-many-arguments
    """Base class for typed wb-cli errors.

    The framework catches this in cli.main() and emits a `{"error": {...}}`
    envelope on stdout. argparse-level errors do NOT raise this — they print
    on stderr and exit with USAGE.

    Attributes
    ----------
    code:
        Stable SCREAMING_SNAKE_CASE identifier with subsystem prefix
        (e.g. ``MQTT_BROKER_DOWN``). Codes are stable across releases.
    message:
        One-line, imperative, English. ≤80 chars where possible.
    hint:
        Optional next step the caller can take. Prefer a concrete
        ``wb-cli ...`` command.
    details:
        Structured context for the caller to inspect programmatically.
        Always an object (never a scalar).
    exit_code:
        Process exit code: one of :class:`ExitCode`.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        code: str,
        message: str,
        *,
        hint: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        exit_code: int = ExitCode.DOMAIN,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details or {}
        self.exit_code = exit_code

    def to_envelope(self) -> dict[str, Any]:
        envelope: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint is not None:
            envelope["hint"] = self.hint
        envelope["details"] = self.details
        return {"error": envelope}
