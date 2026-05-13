"""Parser for mosquitto verbose log entries.

When verbose logging is on (``log_type all`` in
``/etc/mosquitto/conf.d/debug-verbose.conf``), mosquitto emits one line per
PUBLISH it receives::

    1778654671: Received PUBLISH from wb-adc (d0, q1, r1, m53258,
        '/devices/wb-adc/controls/V5_0', ... (5 bytes))

This module converts that line into a structured dict the rest of wb-cli
can hand to a JSON envelope.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

# Captures: source, dup, qos, retain, message_id, topic, payload_size.
# The line emitted by mosquitto looks like:
#   Received PUBLISH from <source> (d<DUP>, q<QOS>, r<RETAIN>, m<MID>, '<TOPIC>', ... (<SIZE> bytes))
# We anchor on "Received PUBLISH from " — a single robust marker.
_PUBLISH_RE = re.compile(
    r"Received PUBLISH from (?P<source>\S+) "
    r"\(d(?P<dup>\d+), q(?P<qos>\d+), r(?P<retain>\d+), m(?P<mid>\d+), "
    r"'(?P<topic>[^']*)', \.\.\. \((?P<size>\d+) bytes\)\)"
)


def parse_publish(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single mosquitto log line. ``None`` if it isn't a PUBLISH entry."""
    match = _PUBLISH_RE.search(line)
    if not match:
        return None
    return {
        "source": match["source"],
        "dup": match["dup"] == "1",
        "qos": int(match["qos"]),
        "retain": match["retain"] == "1",
        "message_id": int(match["mid"]),
        "topic": match["topic"],
        "payload_size": int(match["size"]),
    }


def parse_entries(
    journal_entries: Iterable[Dict[str, Any]],
    *,
    topic: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Walk journald entries (from ``ctx.journal.read``), extract PUBLISH events.

    ``topic`` / ``source``: optional substring filters applied case-sensitively
    after parsing — matches the kind of filtering a user would do with grep on
    the raw mosquitto log.

    Each entry carries the structured fields from :func:`parse_publish` plus
    ``timestamp`` (ISO-8601 UTC, derived from journald's ``__REALTIME_TIMESTAMP``
    microseconds-since-epoch field).
    """
    out: List[Dict[str, Any]] = []
    for entry in journal_entries:
        message = entry.get("MESSAGE") or ""
        publish = parse_publish(message)
        if publish is None:
            continue
        if topic and topic not in publish["topic"]:
            continue
        if source and source not in publish["source"]:
            continue
        publish["timestamp"] = _journal_timestamp(entry)
        out.append(publish)
    return out


def _journal_timestamp(entry: Dict[str, Any]) -> Optional[str]:
    """journald's __REALTIME_TIMESTAMP is microseconds since the unix epoch."""
    raw = entry.get("__REALTIME_TIMESTAMP")
    if raw is None:
        return None
    try:
        from datetime import (  # pylint: disable=import-outside-toplevel
            datetime,
            timezone,
        )

        return datetime.fromtimestamp(int(raw) / 1_000_000, tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return None
