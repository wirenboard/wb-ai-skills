"""Base class for wb-cli command plugins."""

from __future__ import annotations

import argparse
from typing import Optional


class BasePlugin:
    """Base class for all command plugins.

    Subclass and set ``name`` and ``help``, implement ``register`` and
    ``dispatch``.  The module-level ``PLUGIN`` attribute holds the instance.
    """

    name: str = ""
    help: str = ""
    # Plugins that draw their own stderr indicator (progress bar, countdown)
    # should set this to False so the CLI doesn't layer a spinner on top.
    auto_spinner: bool = True

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        raise NotImplementedError

    def dispatch(self, ctx: "CliContext") -> dict:  # noqa: F821
        raise NotImplementedError

    def render(self, result: dict) -> Optional[str]:  # pylint: disable=unused-argument
        """Optional custom human-mode rendering.

        Return a printable string to override the generic table/KV renderer,
        or ``None`` (the default) to fall through to ``wb_cli.render.auto_render``.
        """
        return None
