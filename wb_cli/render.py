"""Human-friendly renderer for command results.

LLM agents / scripts get the JSON envelope via :mod:`wb_cli.output`.
Interactive humans get something compact and scannable, picked here.

Strategy
--------
- A plugin can implement ``render(result) -> Optional[str]`` for a custom
  view; if it returns ``None`` we fall back to :func:`auto_render`.
- :func:`auto_render` recognises two common shapes:

  * a dict with a single list-of-dicts payload (``{"devices": [...], "count": N}``)
    is drawn as an ASCII table.
  * a flat ``{key: scalar}`` dict is drawn as aligned ``key: value`` lines.
- Anything richer falls through to pretty-printed JSON (so the output is
  still parseable as a last resort).

Width is not capped; we trust the terminal.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, List, Mapping, Optional


def auto_render(data: Any) -> str:
    """Pick the best human representation we can derive from shape alone."""
    if not isinstance(data, Mapping):
        return _format_scalar(data)

    list_keys = [
        k
        for k, v in data.items()
        if isinstance(v, list) and all(isinstance(item, Mapping) for item in v)
    ]
    if len(list_keys) == 1:
        return _render_table(data[list_keys[0]])

    if all(not isinstance(v, (Mapping, list)) for v in data.values()):
        return _render_kv(data)

    return _pretty_json(data)


def render_error(code: str, message: str, hint: Optional[str] = None) -> str:
    """A single-line error format for human mode."""
    lines = [f"error [{code}]: {message}"]
    if hint:
        lines.append(f"hint: {hint}")
    return "\n".join(lines)


def _format_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _render_kv(data: Mapping) -> str:
    keys = [k for k in data if k != "count"]
    if not keys:
        return ""
    width = max(len(str(k)) for k in keys)
    return "\n".join(f"{str(k).ljust(width)}  {_format_scalar(data[k])}" for k in keys)


def _render_table(rows: List[Mapping]) -> str:
    if not rows:
        return "(no rows)"
    columns = _columns_in_order(rows)
    widths = {col: max(len(col), *(len(_format_scalar(row.get(col))) for row in rows)) for col in columns}

    header = "  ".join(col.ljust(widths[col]) for col in columns)
    separator = "  ".join("-" * widths[col] for col in columns)
    body = ["  ".join(_format_scalar(row.get(col)).ljust(widths[col]) for col in columns) for row in rows]
    return "\n".join([header, separator, *body])


def _columns_in_order(rows: Iterable[Mapping]) -> List[str]:
    seen: List[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def _pretty_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)
