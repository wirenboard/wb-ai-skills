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
from typing import Any, Dict, Iterable, List, Optional, Sequence

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
    topics: Optional[Sequence[str]] = None,
    sources: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Walk journald entries (from ``ctx.journal.read``), extract PUBLISH events.

    ``topics`` is a list of patterns; an entry matches if **any** pattern
    matches. A pattern is interpreted as:

      * an MQTT-style wildcard if it contains ``+`` or ``#``
        (``/devices/+/controls/K1`` matches ``/devices/wb-mr6c_2/controls/K1``;
        ``/devices/#`` matches everything under ``/devices/``);
      * otherwise a plain substring (``K1`` matches every topic containing
        ``K1`` — handy for grep-style searches).

    ``sources`` is a list of substring patterns matched against the client id.

    Each returned entry carries the structured fields from
    :func:`parse_publish` plus ``timestamp`` (ISO-8601 UTC, derived from
    journald's ``__REALTIME_TIMESTAMP`` microseconds-since-epoch field).
    """
    topic_matchers = [_compile_topic(p) for p in (topics or [])]
    out: List[Dict[str, Any]] = []
    for entry in journal_entries:
        message = entry.get("MESSAGE") or ""
        publish = parse_publish(message)
        if publish is None:
            continue
        if topic_matchers and not any(m(publish["topic"]) for m in topic_matchers):
            continue
        if sources and not any(s in publish["source"] for s in sources):
            continue
        publish["timestamp"] = _journal_timestamp(entry)
        out.append(publish)
    return out


def _compile_topic(pattern: str):
    """Return a predicate ``(str) -> bool`` for one --topic value.

    MQTT wildcards (``+`` / ``#``) compile to anchored regex; everything else
    is a plain substring search.
    """
    if "+" in pattern or "#" in pattern:
        regex = _mqtt_pattern_to_regex(pattern)
        return lambda topic, _r=regex: bool(_r.fullmatch(topic))
    return lambda topic, _p=pattern: _p in topic


def _mqtt_pattern_to_regex(pattern: str) -> "re.Pattern[str]":
    """Translate an MQTT topic pattern into an anchored regex.

    Rules (MQTT 3.1.1 §4.7):
      * ``+`` matches exactly one topic level (no ``/``)
      * ``#`` is the multi-level wildcard, only valid at the end; matches
        every remaining level (including zero levels)
    """
    if pattern == "#":
        return re.compile(r".*")
    if pattern.endswith("/#"):
        prefix = _levels_to_regex(pattern[:-2])
        return re.compile(prefix + r"(?:/.*)?")
    return re.compile(_levels_to_regex(pattern))


def _levels_to_regex(pattern: str) -> str:
    """Join topic levels into a regex, translating ``+`` to ``[^/]+``."""
    return "/".join("[^/]+" if level == "+" else re.escape(level) for level in pattern.split("/"))


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
