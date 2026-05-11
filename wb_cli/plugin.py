"""Base class for wb-cli command plugins."""

from __future__ import annotations

import argparse


class BasePlugin:
    """Base class for all command plugins.

    Subclass and set ``name`` and ``help``, implement ``register`` and
    ``dispatch``.  The module-level ``PLUGIN`` attribute holds the instance.
    """

    name: str = ""
    help: str = ""

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        raise NotImplementedError

    def dispatch(self, ctx: "CliContext") -> dict:  # noqa: F821
        raise NotImplementedError
