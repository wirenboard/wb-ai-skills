"""Top-level CLI: parse argv, dispatch to a plugin, emit result envelope."""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from typing import Optional

from wb_cli import __version__
from wb_cli._registry import BUILTIN_PLUGINS
from wb_cli.context import CliContext
from wb_cli.errors import ExitCode, WbCliError
from wb_cli.output import emit_data, emit_error


def _build_parser(
    exclude: Optional[str] = None,
) -> tuple[argparse.ArgumentParser, argparse._SubParsersAction]:
    parser = argparse.ArgumentParser(
        prog="wb-cli",
        description="Wiren Board controller CLI.",
        epilog="Run `wb-cli <command> --help` for details on each command.",
    )
    parser.add_argument("--version", action="version", version=f"wb-cli {__version__}")
    subparsers = parser.add_subparsers(dest="cmd", metavar="<command>")
    for name, (_, help_text) in sorted(BUILTIN_PLUGINS.items()):
        if name != exclude:
            subparsers.add_parser(name, help=help_text, add_help=False)
    return parser, subparsers


def main(argv: Optional[list[str]] = None) -> int:  # pylint: disable=too-many-return-statements
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help", "--version"):
        root, _ = _build_parser()
        root.parse_args(argv)
        return ExitCode.SUCCESS

    cmd_name = argv[0]
    entry = BUILTIN_PLUGINS.get(cmd_name)
    if entry is None:
        root, _ = _build_parser()
        root.parse_args(argv)  # argparse prints error, exits 2
        return ExitCode.USAGE

    module_path, _ = entry
    try:
        module = importlib.import_module(module_path)
        plug = module.PLUGIN
    except (ImportError, AttributeError) as exc:
        emit_error(
            WbCliError(
                code="PLUGIN_LOAD_FAILED",
                message=f"Cannot load plugin '{cmd_name}': {exc}",
                exit_code=ExitCode.ENVIRONMENT,
            )
        )
        return ExitCode.ENVIRONMENT

    root, subparsers = _build_parser(exclude=cmd_name)
    plug.register(subparsers)
    args = root.parse_args(argv)

    ctx = CliContext(args, quiet=getattr(args, "quiet", False))

    try:
        result = plug.dispatch(ctx)
    except WbCliError as err:
        emit_error(err)
        return err.exit_code
    except KeyboardInterrupt:
        emit_error(
            WbCliError(
                code="INTERRUPTED",
                message="Operation interrupted by signal",
                exit_code=ExitCode.INTERRUPTED,
            )
        )
        return ExitCode.INTERRUPTED
    except Exception as exc:  # pylint: disable=broad-except
        emit_error(
            WbCliError(
                code="INTERNAL",
                message=f"Unhandled exception in '{cmd_name}': {exc}",
                details={"traceback": traceback.format_exc()},
                exit_code=ExitCode.ENVIRONMENT,
            )
        )
        return ExitCode.ENVIRONMENT

    emit_data(result if result is not None else {})
    return ExitCode.SUCCESS


if __name__ == "__main__":
    sys.exit(main())
