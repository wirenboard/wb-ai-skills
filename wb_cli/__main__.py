"""Entry point for ``python3 -m wb_cli``.

The console script ``wb-cli`` declared in pyproject.toml resolves to
:func:`wb_cli.cli.main`; this module exists so ``python3 -m wb_cli`` does
the same thing.
"""

from __future__ import annotations

import sys

from wb_cli.cli import main

if __name__ == "__main__":
    sys.exit(main())
