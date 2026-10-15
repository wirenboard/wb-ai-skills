# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4", "jinja2>=3"]
# ///
"""Standalone validation of a wb-mqtt-serial device template against the driver JSON Schema (Draft7).

Templates come in two forms: plain `config-<device>.json` and `config-<device>.json.jinja`
(Jinja that renders to JSON). A `.jinja` file is rendered first (empty context, includes
resolved from its directory), then validated — same result the driver/CI validate.

Scope: this is a layer-1 (schema/format) pre-check, not the authority. The driver decides
load/no-load and additionally validates what the schema can't express (`condition` expressions,
`write_address`/bit consistency, parameter id/address consistency, subdevice nesting) — check
those separately. Before validating, numeric channel `enum` values are normalized to strings,
mirroring the driver's `FixChannelsEnum` on load, so integer channel enums (which the driver
accepts) are not false-flagged. A `deprecated: true` template is still checked, but flagged as
such — the driver skips validating deprecated templates, so any errors there are schema drift,
not blockers.

The schema is fetched fresh from upstream (`wirenboard/wb-mqtt-serial`, branch/tag via
--ref, default master) on every run, OR taken locally via --schema-dir. There is no cache:
the schema is small and this skill runs where the network is available, so a stale local
copy would only contradict "read the live source". Use --schema-dir for offline / a pinned
version. Does not require the generator to be running and keeps no vendored copy — rules
stay in the source.

Usage (dependencies are installed automatically):
    uv run validate.py config-<device>.json
    uv run validate.py config-<device>.json.jinja                    # Jinja is rendered first
    uv run validate.py --schema-dir ./schemas config-<device>.json   # offline / fixed version
    uv run validate.py --ref v2.259.0 config-<device>.json           # a pinned driver version

Exit codes: 0 — valid; 1 — schema errors found; 2 — operational error (no network,
broken JSON, schema unavailable, jsonschema missing).
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn

RAW_BASE = "https://raw.githubusercontent.com/wirenboard/wb-mqtt-serial"
TEMPLATE_SCHEMA = "wb-mqtt-serial-device-template.schema.json"
COMMON_SCHEMA = "wb-mqtt-serial-confed-common.schema.json"

# Single-line // comments in the driver schemas. Leave // inside strings alone (e.g. "http://").
_COMMENT_RE = re.compile(r'(?<!["\w:])//[^\n]*')
# channel_name pattern from the schema — characters forbidden in an MQTT topic.
_CHANNEL_NAME_PATTERN = "^[^$#+\\/\"']+$"


def die(msg: str) -> NoReturn:
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def _strip_comments(text: str) -> str:
    return _COMMENT_RE.sub("", text)


def _fetch(ref: str, name: str) -> str:
    """Download one schema file fresh from upstream. No caching: the schema is small,
    this skill runs where the network is available, and a stale local copy would only
    contradict "read the live source". For offline / a pinned version, use --schema-dir."""
    url = f"{RAW_BASE}/{ref}/{name}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — fixed https host
            text = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as e:
        die(
            f"ERROR: could not download schema {url}: {e}\n"
            f"Check network/ref, or use --schema-dir with local schemas."
        )
    return text


def _read_local(schema_dir: Path, name: str) -> str:
    path = schema_dir / name
    if not path.is_file():
        die(
            f"ERROR: schema not found: {path}. The directory must contain both files:\n"
            f"  {TEMPLATE_SCHEMA}\n  {COMMON_SCHEMA}"
        )
    return path.read_text(encoding="utf-8")


def load_schema(ref: str, schema_dir: "Path | None") -> "tuple[dict, str]":
    """Return (merged schema, human-readable source)."""
    if schema_dir is not None:
        template_raw = _read_local(schema_dir, TEMPLATE_SCHEMA)
        common_raw = _read_local(schema_dir, COMMON_SCHEMA)
        source = f"local: {schema_dir}"
    else:
        template_raw = _fetch(ref, TEMPLATE_SCHEMA)
        common_raw = _fetch(ref, COMMON_SCHEMA)
        source = f"github.com/wirenboard/wb-mqtt-serial@{ref}"

    template = json.loads(_strip_comments(template_raw))
    common = json.loads(_strip_comments(common_raw))

    # $ref in template points at #/definitions/... from common — inject them.
    defs = template.setdefault("definitions", {})
    for key, value in common.get("definitions", {}).items():
        defs.setdefault(key, value)
    return template, source


def leaf_errors(err):
    """Descend an anyOf/oneOf to the concrete leaf errors of the branch the
    instance is closest to.

    "Closest" = the branch whose errors reach *deepest* into the instance (it
    validated furthest before failing), tie-broken by *fewest* errors (the
    tightest match). Recursing per branch resolves nested per-channel oneOfs, so
    each channel is reported through the channel type it actually is — a
    numeric-register channel is not also flagged with a bogus "address must be a
    string" from a text-channel branch it never took.

    One device/channel-oneOf branch validates the whole device, so picking a
    single branch keeps *every* channel's error — it does not mask one channel
    with another (the bug in the earlier "global deepest leaf" filter). Selecting
    by error *count* alone is what surfaced a bogus "'device_type' is required"
    instead of "1 is not of type 'string'"; depth-first fixes that.
    """
    if not err.context:
        return [err]
    branches: dict = {}
    for sub in err.context:
        idx = sub.schema_path[0] if sub.schema_path else None
        branches.setdefault(idx, []).append(sub)
    expanded = [[leaf for s in subs for leaf in leaf_errors(s)] for subs in branches.values()]

    def score(leaves):
        depth = max((len(leaf.absolute_path) for leaf in leaves), default=0)
        return (depth, -len(leaves))  # deepest first, then fewest errors

    return max(expanded, key=score)


def prune_ancestors(errors):
    """Drop container-level noise while keeping the most specific error per path.

    An error whose instance path is a *strict ancestor* of another error's path
    is only a summary of a deeper, more specific failure — e.g. "'device_type' is
    a required property" on the channel object when the real error is "1 is not of
    type 'string'" at ``channels/0/enum/0``. Drop the ancestor, keep the leaf.

    The check is per instance location (path prefix), so a deep error in one
    channel never masks a shallower real error in another — unlike a global
    "deepest wins" filter, which lets ``channels/1/enum/0`` (depth 5) hide a
    forbidden-topic-char and a bad ``reg_type`` in ``channels/0`` (depth 4).
    """
    paths = [tuple(e.absolute_path) for e in errors]

    def has_descendant(p):
        return any(len(q) > len(p) and q[: len(p)] == p for q in paths)

    return [e for e, p in zip(errors, paths) if not has_descendant(p)]


def humanize(err) -> str:
    """Readable message for common cryptic cases (otherwise the original)."""
    if err.validator == "pattern" and err.validator_value == _CHANNEL_NAME_PATTERN:
        return (
            f"{err.instance!r}: channel name contains characters forbidden in an "
            f"MQTT topic (one of: $ # + / \\ \" ')"
        )
    return err.message


def render_jinja(path: Path) -> str:
    """Render a .json.jinja template to text (empty context; includes resolved from
    the file's directory). WB templates are self-contained and render with an empty
    context. If one needs build-time context/filters, render it with the repo tooling."""
    try:
        # Lazy: jinja2 is needed only for .jinja input.
        from jinja2 import FileSystemLoader  # pylint: disable=import-outside-toplevel
        from jinja2.sandbox import (  # pylint: disable=import-outside-toplevel
            SandboxedEnvironment,
        )
    except ImportError:
        die(
            "ERROR: jinja2 is required to validate a .json.jinja template. "
            "Run via `uv run validate.py …` or install it: pip install jinja2"
        )
    try:
        # Sandboxed: a template under review may come from a third party, and plain
        # Jinja can reach Python internals (SSTI) and run arbitrary code.
        env = SandboxedEnvironment(loader=FileSystemLoader(str(path.parent)))
        return env.get_template(path.name).render()
    # TemplateError and anything the render raises
    except Exception as e:  # pylint: disable=broad-exception-caught
        die(
            f"ERROR: could not render Jinja template {path}: {type(e).__name__}: {e}\n"
            f"If it relies on build-time context or filters, render it with the wb-mqtt-serial "
            f"repo tooling (`make dump-templates`) and run validate.py on the rendered JSON."
        )


def load_template(path: Path) -> dict:
    """Parse a template into a dict. A .json.jinja file is rendered first. The
    template may also carry // comments (WB sources) — strip those before parsing."""
    is_jinja = path.name.endswith(".jinja")
    text = render_jinja(path) if is_jinja else path.read_text(encoding="utf-8")
    if is_jinja:
        print(f"Template: {path} (rendered from Jinja)")
    try:
        return json.loads(_strip_comments(text))
    except json.JSONDecodeError as e:
        die(f"ERROR: {'rendered ' if is_jinja else ''}template {path} is not valid JSON: {e}")


def fix_channels_enum(node) -> int:
    """Mirror the driver's FixChannelsEnum (serial_config.cpp): convert numeric channel
    `enum` values to their string form, recursively, in place. The driver applies this on
    disk-load (TDeviceTemplate::GetTemplate) *before* schema-validating, so a template with
    integer channel enums (e.g. [0, 1, 2]) loads fine even though the schema declares channel
    enum items as `string`. Doing the same here keeps validate.py in step with what the driver
    accepts instead of false-flagging them. Only channel `enum` is touched (not parameter
    `enum`, which the schema already allows as integers). Returns the count normalized."""

    def is_num(v):
        # bool is a subclass of int in Python; jsoncpp's isNumeric() is false for bool.
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    count = 0
    if isinstance(node, dict):
        channels = node.get("channels")
        if isinstance(channels, list):
            for channel in channels:
                if isinstance(channel, dict) and isinstance(channel.get("enum"), list):
                    if any(is_num(v) for v in channel["enum"]):
                        channel["enum"] = [str(v) if is_num(v) else v for v in channel["enum"]]
                        count += 1
        for value in node.values():
            count += fix_channels_enum(value)
    elif isinstance(node, list):
        for item in node:
            count += fix_channels_enum(item)
    return count


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate a wb-mqtt-serial template against the driver JSON Schema."
    )
    ap.add_argument(
        "template",
        type=Path,
        help="path to config-<device>.json or config-<device>.json.jinja",
    )
    ap.add_argument(
        "--schema-dir",
        type=Path,
        default=None,
        help=f"directory with local {TEMPLATE_SCHEMA} and {COMMON_SCHEMA} (offline)",
    )
    ap.add_argument(
        "--ref", default="master", help="upstream git ref of the schema (branch/tag, default master)"
    )
    args = ap.parse_args()

    try:
        from jsonschema import (  # pylint: disable=import-outside-toplevel
            Draft7Validator,
        )
    except ImportError:
        die(
            "ERROR: the jsonschema package is required. Run via `uv run validate.py …` "
            "or install it: pip install jsonschema"
        )

    if not args.template.is_file():
        die(f"ERROR: template not found: {args.template}")

    template_data = load_template(args.template)
    normalized = fix_channels_enum(template_data)  # mirror the driver's FixChannelsEnum on load

    schema, source = load_schema(args.ref, args.schema_dir)
    print(f"Schema: {source}")
    if template_data.get("deprecated"):
        print(
            "Note: this template is `deprecated: true` — the driver SKIPS schema validation "
            "for deprecated templates, so any errors below are drift against the current "
            "schema, not something the driver enforces."
        )
    if normalized:
        print(
            f"Normalized {normalized} channel enum(s) with numeric values to strings "
            f"(mirrors the driver's FixChannelsEnum on load)."
        )

    leaves = []
    for top in Draft7Validator(schema).iter_errors(template_data):
        leaves.extend(leaf_errors(top))
    leaves = prune_ancestors(leaves)

    # Dedupe by (path, message), stable sort by path.
    seen, unique = set(), []
    for err in leaves:
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        msg = humanize(err)
        if (loc, msg) not in seen:
            seen.add((loc, msg))
            unique.append((loc, msg))
    unique.sort(key=lambda x: x[0])

    if not unique:
        print(f"OK: {args.template} is valid against the driver schema.")
        print(
            "Reminder: this is a layer-1 (schema/format) pre-check, not the authority — the "
            "wb-mqtt-serial driver decides load/no-load and also checks what the schema can't: "
            "condition expressions, write_address/bit consistency, parameter id/address "
            "consistency, subdevice nesting. Check layer 2 (standard/units) and layer 3 "
            "(driver behaviour) separately — see references/."
        )
        return 0

    print(f"SCHEMA ERRORS FOUND: {len(unique)}\n")
    for loc, msg in unique:
        print(f"  x {loc}: {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
