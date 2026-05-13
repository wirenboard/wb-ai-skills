"""Scan ``wb_cli/commands/`` and emit a fresh ``wb_cli/_registry.py``.

Run via ``make registry``.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

import wb_cli.commands as commands_pkg


def collect() -> list[tuple[str, str, str]]:
    """Return [(name, module_path, help_text), ...] sorted by name.

    Each command exposes a ``PLUGIN`` attribute. Single-file commands put it
    in ``wb_cli.commands.<name>``; package commands (e.g. ``serial``) re-export
    ``PLUGIN`` from their ``__init__.py``. Either way the registry stores
    ``wb_cli.commands.<name>`` — the ``_plugin`` submodule is an implementation
    detail and never appears in the registry.
    """
    found: list[tuple[str, str, str]] = []
    for _, mod_name, _ in pkgutil.iter_modules(
        commands_pkg.__path__,
        commands_pkg.__name__ + ".",
    ):
        try:
            module = importlib.import_module(mod_name)
        except ImportError:
            continue
        plug = getattr(module, "PLUGIN", None)
        if plug is None:
            continue
        found.append((plug.name, mod_name, plug.help))
    found.sort()
    return found


def render(plugins: list[tuple[str, str, str]]) -> str:
    lines = [
        '"""Plugin registry — maps command names to (module_path, help_text).',
        "",
        "Regenerate via ``make registry`` (runs ``python3 -m wb_cli._gen_registry``).",
        '"""',
        "",
        "# {name: (module_path, help_text)}",
        "BUILTIN_PLUGINS: dict = {",
    ]
    for name, module, help_text in plugins:
        lines.append(f'    "{name}": ("{module}", "{help_text}"),')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    target = Path(__file__).parent / "_registry.py"
    plugins = collect()
    target.write_text(render(plugins), encoding="utf-8")
    print(f"wrote {target} ({len(plugins)} plugins)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
