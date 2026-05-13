"""``wb-cli serial`` — serial port operations.

A subpackage because this group has more than four subcommands.
The plugin entry point is in ``_plugin.py`` and re-exported here so the
generated registry can address every command uniformly as
``wb_cli.commands.<name>`` regardless of whether it is a module or a package.
"""

from wb_cli.commands.serial._plugin import PLUGIN

__all__ = ["PLUGIN"]
