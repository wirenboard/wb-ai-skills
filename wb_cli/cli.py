"""Top-level CLI: parse argv, dispatch to a plugin, emit result envelope."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import os
import sys
import traceback
from typing import Optional

from wb_cli import __version__, render
from wb_cli._registry import BUILTIN_PLUGINS
from wb_cli.context import CliContext
from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib.progress import Spinner
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
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="machine mode: emit only the JSON envelope, no spinner/progress",
    )
    parser.add_argument(
        "--human",
        action="store_true",
        dest="human_mode",
        help="human mode: render tables / key-value pairs instead of JSON",
    )
    subparsers = parser.add_subparsers(dest="cmd", metavar="<command>")
    for name, (_, help_text) in sorted(BUILTIN_PLUGINS.items()):
        if name != exclude:
            subparsers.add_parser(name, help=help_text, add_help=False)
    return parser, subparsers


def _pop_global_flags(argv: list) -> tuple[list, Optional[str]]:
    """Strip leading global flags and return them.

    Returns ``(remaining_argv, output_override)`` where output_override is
    ``"json"`` / ``"human"`` / ``None`` (no override).
    """
    override: Optional[str] = None
    remaining = []
    for token in argv:
        if token == "--json":
            override = "json"
        elif token == "--human":
            override = "human"
        else:
            remaining.append(token)
    return remaining, override


def _resolve_output_mode(flag_override: Optional[str]) -> str:
    """Decide between JSON and human output.

    Priority: CLI flag > ``WB_CLI_OUTPUT`` env > stdout TTY heuristic.
    Default for a non-TTY stdout (pipes, SSH without ``-t``, files) is JSON,
    so LLM agents and scripts get machine-readable output without thinking.
    """
    if flag_override:
        return flag_override
    env = os.environ.get("WB_CLI_OUTPUT", "").strip().lower()
    if env in ("json", "human"):
        return env
    return "human" if sys.stdout.isatty() else "json"


def main(argv: Optional[list[str]] = None) -> int:  # pylint: disable=too-many-return-statements,too-many-locals
    argv = list(sys.argv[1:] if argv is None else argv)
    argv, output_override = _pop_global_flags(argv)
    output_mode = _resolve_output_mode(output_override)

    if not argv:
        root, _ = _build_parser()
        root.print_help()
        return ExitCode.SUCCESS

    if argv[0] in ("-h", "--help", "--version"):
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

    # `wb-cli <plugin>` with no subcommand: argparse leaves args.subcmd=None
    # because we don't mark subparsers required (we want the help screen, not
    # a usage error). Re-parse with --help so the user sees the action list.
    if hasattr(args, "subcmd") and args.subcmd is None:
        root.parse_args([cmd_name, "--help"])
        return ExitCode.SUCCESS

    ctx = CliContext(args, quiet=getattr(args, "quiet", False))

    label = f"{cmd_name} {args.subcmd}" if getattr(args, "subcmd", None) else cmd_name
    spinner_ctx = Spinner(label) if getattr(plug, "auto_spinner", True) else contextlib.nullcontext()

    try:
        with spinner_ctx:
            result = plug.dispatch(ctx)
    except WbCliError as err:
        if output_mode == "human":
            print(render.render_error(err.code, err.message, err.hint), file=sys.stderr)
        else:
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

    payload = result if result is not None else {}
    if output_mode == "human":
        custom = plug.render(payload) if isinstance(payload, dict) else None
        print(custom if custom is not None else render.auto_render(payload))
    else:
        emit_data(payload)
    return ExitCode.SUCCESS


if __name__ == "__main__":
    sys.exit(main())
