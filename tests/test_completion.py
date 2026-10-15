"""The checked-in bash completion must match the current command tree.

Mirrors the ``make completion`` output; regenerate with it after adding or
changing a command. The Debian build regenerates too, so this only guards the
copy committed to the repo.
"""

from __future__ import annotations

from pathlib import Path

from wb_cli import _gen_completion
from wb_cli._registry import BUILTIN_PLUGINS

ROOT = Path(__file__).resolve().parent.parent
COMPLETION = ROOT / "data" / "bash-completion" / "wb-cli"


def test_completion_is_up_to_date():
    generated = _gen_completion.render(_gen_completion.collect())
    on_disk = COMPLETION.read_text(encoding="utf-8")
    assert (
        generated == on_disk
    ), "data/bash-completion/wb-cli is stale. Run `make completion` and commit the result."


def test_completion_covers_every_command():
    text = COMPLETION.read_text(encoding="utf-8")
    command_line = text.split("local commands=", 1)[1].splitlines()[0]
    for name in BUILTIN_PLUGINS:
        assert name in command_line, f"command {name!r} missing from the completion's command list"
        assert (
            f"opts_{name.replace('-', '_')}=" in text
        ), f"option table for command {name!r} missing from the completion"
