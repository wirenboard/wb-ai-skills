"""``wb-cli dev`` — the one entry point for devices and controls.

Addressing follows the wb-rules convention: ``<device>/<control>``.
Everything is one positional plus an optional value::

    wb-cli dev                                 # every <device>/<control> with type/readonly/value
    wb-cli dev <device>                        # controls of one device (same columns)
    wb-cli dev <device>/<control>              # read one
    wb-cli dev <device>/<control> <value>      # write one
    wb-cli dev --all                           # include system_* devices in the list

No subcommands, no separate ``devices`` plugin — just one verb, one argument.
"""

from __future__ import annotations

import argparse
import shutil
from typing import Any, Dict, List, Tuple

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class DevPlugin(BasePlugin):
    name = "dev"
    help = "list controls (all / one device) and read or write a single one"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description=(
                "One verb to work with WB devices and their controls.\n"
                "  (no args)              every <device>/<control> on the bus + metadata\n"
                "  <device>               controls of one device + metadata\n"
                "  <device>/<control>     read this control\n"
                "  <device>/<control> X   write X to this control\n"
                "Addresses use the wb-rules form `<device>/<control>` — same as\n"
                '`dev["<device>"]["<control>"]` inside a wb-rules script.'
            ),
            epilog=(
                "Examples:\n"
                "  wb-cli dev                                    # full bus table\n"
                "  wb-cli dev | grep mr6c                        # filter client-side\n"
                "  wb-cli dev wb-mr6c_2                          # one device\n"
                "  wb-cli dev wb-mr6c_2/K1                       # read relay state\n"
                "  wb-cli dev wb-mr6c_2/K1 1                     # turn the relay on\n"
                "  wb-cli dev 'wb-mdm3_5/Channel 1 Dimming Level' 30    # quote spaces\n"
                "  wb-cli dev custom-dev/mode 'auto night'              # quote values too\n"
                "\n"
                "Over SSH double-quote, since the controller's shell sees the same string:\n"
                "  ssh root@HOST \"wb-cli --json dev 'wb-mdm3_5/Channel 1 Dimming Level' 30\"\n"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(
            "address",
            nargs="?",
            default=None,
            help="<device> or <device>/<control>; omit to list everything",
        )
        parser.add_argument(
            "value",
            nargs="?",
            default=None,
            help="value to publish (only with <device>/<control>)",
        )
        parser.add_argument(
            "--all",
            dest="show_all",
            action="store_true",
            help="(list mode) include `system_*` devices; hidden by default",
        )

    def dispatch(self, ctx) -> dict:
        addr = ctx.args.address
        if addr is None:
            return _list_all(ctx)
        if "/" in addr:
            device, control = _split_address(addr)
            if ctx.args.value is None:
                return _get(ctx, device, control)
            return _set(ctx, device, control, ctx.args.value)
        # bare <device>: list controls of that one device
        if ctx.args.value is not None:
            raise WbCliError(
                code="DEV_INVALID_ADDRESS",
                message=(f"To write, address must be '<device>/<control>', got '{addr}' with value"),
                hint="Did you mean: wb-cli dev " + addr + "/<control> <value>?",
                details={"address": addr, "value": ctx.args.value},
                exit_code=ExitCode.USAGE,
            )
        return _controls_of(ctx, addr)

    def render(self, result):
        if "controls" in result and "device" in result:
            return _render_table(result["controls"], device=result["device"])
        if "controls" in result:
            return _render_table(result["controls"])
        if result.get("ok"):
            return f"ok  {result['device']}/{result['control']} := {result['value']}"
        flags = "ro" if result.get("readonly") else "rw"
        ctype = result.get("type") or "?"
        return f"{result['value']}  ({ctype}, {flags})"


# --------------------------------------------------------------------------- #
# list / inspect
# --------------------------------------------------------------------------- #


def _list_all(ctx) -> dict:
    """Every <device>/<control> on the bus, with value + type + readonly + error."""
    vals = ctx.mqtt.subscribe("/devices/+/controls/+", timeout=5.0)
    metas = ctx.mqtt.subscribe("/devices/+/controls/+/meta/+", timeout=5.0)
    controls = _build_full(vals, metas)
    if not getattr(ctx.args, "show_all", False):
        controls = [c for c in controls if not c["device"].startswith("system_")]
    return {"controls": controls, "count": len(controls)}


def _controls_of(ctx, device: str) -> dict:
    """Controls of one device, with the same columns as the full list."""
    vals = ctx.mqtt.subscribe(f"/devices/{device}/controls/+", timeout=5.0)
    if not vals:
        raise WbCliError(
            code="DEV_DEVICE_NOT_FOUND",
            message=f"Device '{device}' not found",
            hint="Run `wb-cli dev` (or `dev --all`) for the available devices.",
            details={"device": device},
            exit_code=ExitCode.DOMAIN,
        )
    metas = ctx.mqtt.subscribe(f"/devices/{device}/controls/+/meta/+", timeout=5.0)
    controls = _build_full(vals, metas)
    return {"device": device, "controls": controls, "count": len(controls)}


# --------------------------------------------------------------------------- #
# get / set
# --------------------------------------------------------------------------- #


def _get(ctx, device: str, control: str) -> dict:
    topic = f"/devices/{device}/controls/{control}"
    msgs = ctx.mqtt.subscribe(topic, timeout=5.0)
    if not msgs:
        _raise_control_not_found(device, control)
    meta = ctx.mqtt.subscribe(f"{topic}/meta/+", timeout=5.0)
    readonly = any(t.endswith("/readonly") and p == "1" for t, p in meta)
    ctrl_type = next((p for t, p in meta if t.endswith("/type")), None)
    return {
        "device": device,
        "control": control,
        "value": msgs[0][1],
        "type": ctrl_type,
        "readonly": readonly,
    }


def _set(ctx, device: str, control: str, value: str) -> dict:
    base = f"/devices/{device}/controls/{control}"
    existing = ctx.mqtt.subscribe(base, timeout=3.0)
    if not existing:
        _raise_control_not_found(device, control)
    meta = ctx.mqtt.subscribe(f"{base}/meta/+", timeout=3.0)
    if any(t.endswith("/readonly") and p == "1" for t, p in meta):
        raise WbCliError(
            code="DEV_CONTROL_READONLY",
            message=f"Control '{device}/{control}' is read-only",
            details={"device": device, "control": control},
            exit_code=ExitCode.DOMAIN,
        )
    ctx.mqtt.publish(f"{base}/on", value)
    return {
        "device": device,
        "control": control,
        "value": value,
        "ok": True,
    }


# --------------------------------------------------------------------------- #
# parsing & errors
# --------------------------------------------------------------------------- #


def _split_address(address: str) -> Tuple[str, str]:
    device, _, control = address.partition("/")
    if not device or not control:
        raise WbCliError(
            code="DEV_INVALID_ADDRESS",
            message=f"Address must be '<device>/<control>', got '{address}'",
            details={"address": address},
            exit_code=ExitCode.USAGE,
        )
    return device, control


def _raise_control_not_found(device: str, control: str) -> None:
    raise WbCliError(
        code="DEV_CONTROL_NOT_FOUND",
        message=f"Control '{device}/{control}' not found",
        hint=f"Run `wb-cli dev {device}` to see available controls.",
        details={"device": device, "control": control},
        exit_code=ExitCode.DOMAIN,
    )


# --------------------------------------------------------------------------- #
# table building
# --------------------------------------------------------------------------- #


def _build_full(
    vals: List[Tuple[str, str]],
    metas: List[Tuple[str, str]],
) -> List[Dict[str, Any]]:
    """Merge values + metas into a list of {device, control, value, type, readonly, error}."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for topic, payload in vals:
        parts = topic.split("/", 4)
        if len(parts) < 5 or parts[1] != "devices" or parts[3] != "controls":
            continue
        device, control = parts[2], parts[4]
        out.setdefault((device, control), {"device": device, "control": control})
        out[(device, control)]["value"] = payload

    for topic, payload in metas:
        parts = topic.split("/")
        if len(parts) < 7:
            continue
        device, control, meta_key = parts[2], parts[4], parts[6]
        out.setdefault((device, control), {"device": device, "control": control})
        if meta_key == "type":
            out[(device, control)]["type"] = payload
        elif meta_key == "readonly":
            out[(device, control)]["readonly"] = payload == "1"
        elif meta_key == "error":
            out[(device, control)]["error"] = payload or None
        elif meta_key == "order" and payload.isdigit():
            out[(device, control)]["order"] = int(payload)

    rows = sorted(
        out.values(),
        key=lambda c: (c["device"], c.get("order", 999), c["control"]),
    )
    for c in rows:
        c.pop("order", None)
        c.setdefault("value", "")
        c.setdefault("type", None)
        c.setdefault("readonly", False)
        c.setdefault("error", None)
    return rows


def _render_table(  # pylint: disable=too-many-locals
    rows: List[Dict[str, Any]], *, device: str = None
) -> str:
    """Render the controls list as a compact fixed-width table.

    Keeps the line under ~120 columns by merging type+flags into a single
    ``type/rw`` column and omitting the ``error`` column when no row has an
    error. ``device``: when given, the "address" column shows just
    ``<control>`` instead of ``<device>/<control>``.
    """
    if not rows:
        return "(no controls)"

    has_errors = any(r.get("error") for r in rows)
    term_width = max(60, shutil.get_terminal_size((120, 24)).columns)

    def addr(row):
        return row["control"] if device else f"{row['device']}/{row['control']}"

    def value(row):
        return str(row.get("value", "")).replace("\n", " ").replace("\t", " ")

    def kind(row):
        ctype = row.get("type") or "?"
        return f"{ctype}/{'ro' if row.get('readonly') else 'rw'}"

    columns = [
        ("address", addr, 40),  # name, getter, max-width
        ("value", value, 0),  # value soaks up whatever room is left
        ("type", kind, 20),
    ]
    if has_errors:
        columns.append(("error", lambda r: r.get("error") or "", 30))

    # First measure natural widths, then squeeze `value` to fit the terminal.
    natural = {name: max(len(name), *(len(get(r)) for r in rows)) for name, get, _ in columns}
    for name, _, cap in columns:
        if cap and natural[name] > cap:
            natural[name] = cap

    overhead = 2 * (len(columns) - 1)  # "  " separators
    other = sum(natural[name] for name, _, _ in columns if name != "value")
    natural["value"] = max(5, term_width - overhead - other)

    def fit(text: str, width: int) -> str:
        return text if len(text) <= width else text[: width - 1] + "…"

    header = "  ".join(name.ljust(natural[name]) for name, _, _ in columns)
    sep = "  ".join("-" * natural[name] for name, _, _ in columns)
    body = [
        "  ".join(fit(get(r), natural[name]).ljust(natural[name]) for name, get, _ in columns) for r in rows
    ]
    return "\n".join([header, sep, *body])


PLUGIN = DevPlugin()
