"""Output rendering — JSON envelope on stdout."""

from __future__ import annotations

import json
import sys
from typing import IO, Any

from wb_cli.errors import WbCliError


def emit_data(data: dict, *, stream: IO[str] = sys.stdout) -> None:
    """Print ``{"data": ...}`` envelope. *data* must be a dict."""
    if not isinstance(data, dict):
        raise TypeError(f"data must be a dict, got {type(data).__name__}")
    _emit({"data": data}, stream)


def emit_error(err: WbCliError, *, stream: IO[str] = sys.stdout) -> None:
    """Print ``{"error": ...}`` envelope on stdout."""
    _emit(err.to_envelope(), stream)


def _emit(envelope: dict[str, Any], stream: IO[str]) -> None:
    json.dump(envelope, stream, ensure_ascii=False, indent=2, sort_keys=False)
    stream.write("\n")
