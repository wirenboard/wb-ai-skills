"""Helpers for reading wb-mqtt-serial device templates from the filesystem.

Templates ship as JSON files in two directories:

  * ``/etc/wb-mqtt-serial.conf.d/templates/`` — custom (user-supplied), checked
    first; survives ``apt upgrade``.
  * ``/usr/share/wb-mqtt-serial/templates/`` — packaged with wb-mqtt-serial.

``wb-mqtt-serial`` itself does not expose a "list templates" RPC, so plugins
read them locally. Going through this module instead of ``ctx.shell.run([cat,
find, grep])`` keeps the I/O testable and free of subprocess parsing quirks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional

CUSTOM_DIR = Path("/etc/wb-mqtt-serial.conf.d/templates")
PACKAGED_DIR = Path("/usr/share/wb-mqtt-serial/templates")
SEARCH_DIRS: tuple[Path, ...] = (CUSTOM_DIR, PACKAGED_DIR)


def _dirs(search_dirs: Optional[Iterable[Path]]) -> Iterable[Path]:
    """Resolve the directory tuple. ``None`` (the default) picks up the
    current value of ``SEARCH_DIRS`` so tests can monkeypatch it.
    """
    return SEARCH_DIRS if search_dirs is None else search_dirs


def list_template_names(search_dirs: Optional[Iterable[Path]] = None) -> List[str]:
    """Return every ``*.json`` filename across the search dirs, sorted.

    Custom names shadow packaged ones (same filename → custom wins) so callers
    see one entry per template.
    """
    seen: dict[str, str] = {}
    for directory in _dirs(search_dirs):
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if entry.is_file() and entry.suffix == ".json":
                seen.setdefault(entry.name, entry.name)
    return sorted(seen)


def read_template(
    template_id: str,
    search_dirs: Optional[Iterable[Path]] = None,
) -> Optional[dict]:
    """Load and parse a single template by filename (with or without ``.json``).

    Returns ``None`` if no file matches; raises ``json.JSONDecodeError`` if the
    file is found but malformed (caller decides how to surface that).
    """
    filename = template_id if template_id.endswith(".json") else f"{template_id}.json"
    for directory in _dirs(search_dirs):
        path = directory / filename
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def find_template_by_field(
    field: str,
    value: str,
    search_dirs: Optional[Iterable[Path]] = None,
) -> Optional[dict]:
    """Return the first template whose top-level ``field`` equals ``value``.

    Skips deprecated templates (path contains ``deprecated``) unless that is
    the only candidate. Custom templates win over packaged ones because
    ``SEARCH_DIRS`` is ordered.
    """
    candidates: list[Path] = []
    fallback: list[Path] = []
    for directory in _dirs(search_dirs):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get(field) != value:
                continue
            if "deprecated" in str(path).lower():
                fallback.append(path)
            else:
                candidates.append(path)
    chosen = candidates or fallback
    if not chosen:
        return None
    try:
        return json.loads(chosen[0].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def find_template(
    identifier: str,
    search_dirs: Optional[Iterable[Path]] = None,
) -> Optional[dict]:
    """Find a template by either ``device_type`` or scan ``signature``.

    Mirrors what ``wb-cli serial add-devices`` needs when matching scan results
    to a template — try device_type first (config-level), fall back to
    signature (the wb-device-manager scan field).
    """
    for field in ("device_type", "signature"):
        template = find_template_by_field(field, identifier, search_dirs)
        if template is not None:
            return template
    return None
