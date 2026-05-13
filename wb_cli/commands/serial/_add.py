"""``wb-cli serial add-devices`` — append discovered/named devices to the config.

Three modes:

  * ``--device-type + --slave-id``: a single named device, no scan.
  * ``--scan-results JSON``: explicit scan output, for scripting.
  * (default): the retained ``/wb-device-manager/state`` from the last scan.

Bus-side fixups run before adding: baud-rate mismatch (Modbus FC6 reg 110)
and slave_id collision (Fast Modbus by SN if available, standard FC6 reg 128
as a fallback for config-only conflicts).
"""

from __future__ import annotations

import json

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib import serial_bus, serial_port, templates
from wb_cli.lib.progress import ProgressBar

_SERIAL_CONF_PATH = "/etc/wb-mqtt-serial.conf"
_INHERITED_UART_KEYS = ("baud_rate", "parity", "data_bits", "stop_bits")


def add_devices(ctx) -> dict:  # pylint: disable=too-many-locals
    """Top-level dispatcher for ``add-devices`` — picks the right mode.

    With ``--device-type``: single named device on the explicit ``--port``.

    Without ``--device-type``: scan-results flow. If ``--port`` is given,
    add only to that port; otherwise iterate every port mentioned in the
    scan results and add to each in one go.
    """
    device_type = getattr(ctx.args, "device_type", None)
    slave_id = getattr(ctx.args, "slave_id", None)
    scan_results_arg = getattr(ctx.args, "scan_results", None)

    content = _load_config(ctx)

    if device_type is not None:
        if not ctx.args.port:
            raise WbCliError(
                code="MODBUS_ADD_MISSING_PORT",
                message="--port is required with --device-type",
                hint="Specify the target port, e.g. --port /dev/ttyRS485-1.",
                exit_code=ExitCode.USAGE,
            )
        target_port = _load_target_port(content, ctx.args.port)
        existing_slave_ids = {d.get("slave_id") for d in target_port.get("devices", [])}
        added, skipped, warnings = _add_one_named(
            target_port,
            existing_slave_ids,
            device_type=device_type,
            slave_id=slave_id,
        )
        result = _save_and_envelope(ctx, content, [ctx.args.port], added, skipped, warnings)
        return result

    scan_devices = _resolve_scan_devices(ctx, scan_results_arg)
    ports_to_process = _resolve_ports_to_process(ctx, scan_devices)
    port_explicit = bool(ctx.args.port)

    aggregated_added: list = []
    aggregated_skipped: list = []
    aggregated_warnings: list = []
    for port_path in ports_to_process:
        try:
            target_port = _load_target_port(content, port_path)
        except WbCliError:
            if port_explicit:
                # User typed the wrong port → surface the error.
                raise
            aggregated_warnings.append(f"{port_path}: not present in {_SERIAL_CONF_PATH} — skipped")
            continue
        existing_slave_ids = {d.get("slave_id") for d in target_port.get("devices", [])}
        port_added, port_skipped, port_warnings = _add_from_scan(
            ctx,
            target_port,
            existing_slave_ids,
            scan_devices,
            port_path=port_path,
        )
        aggregated_added.extend({**row, "port": port_path} for row in port_added)
        aggregated_skipped.extend({"slave_id": sid, "port": port_path} for sid in port_skipped)
        aggregated_warnings.extend(f"{port_path}: {w}" for w in port_warnings)

    return _save_and_envelope(
        ctx,
        content,
        ports_to_process,
        aggregated_added,
        aggregated_skipped,
        aggregated_warnings,
    )


def _save_and_envelope(  # pylint: disable=too-many-arguments
    ctx,
    content: dict,
    ports: list,
    added: list,
    skipped: list,
    warnings: list,
) -> dict:
    if added:
        ctx.rpc.call(
            "confed/Editor/Save",
            {"path": _SERIAL_CONF_PATH, "content": content},
        )
    result = {
        "port": ctx.args.port if ctx.args.port else None,
        "ports": ports,
        "added": added,
        "skipped": skipped,
        "count": len(added),
    }
    if warnings:
        result["warnings"] = warnings
    return result


def _resolve_ports_to_process(ctx, scan_devices: list) -> list:
    """Pick which ports we'll iterate over for the scan-results flow.

    With ``--port``: just that port. Without: every unique port present in
    the scan results.
    """
    if ctx.args.port:
        return [ctx.args.port]
    seen = []
    for dev in scan_devices:
        path = dev.get("port", {}).get("path")
        if path and path not in seen:
            seen.append(path)
    if not seen:
        raise WbCliError(
            code="MODBUS_ADD_EMPTY",
            message="Scan results contain no devices with a port — nothing to add.",
            hint="Run `wb-cli serial wb-scan` first, or pass --port explicitly.",
            exit_code=ExitCode.DOMAIN,
        )
    return seen


# --------------------------------------------------------------------------- #
# Mode 1: single named device
# --------------------------------------------------------------------------- #


def _add_one_named(
    target_port: dict,
    existing_slave_ids: set,
    *,
    device_type: str,
    slave_id,
) -> tuple[list, list, list]:
    if slave_id is None:
        raise WbCliError(
            code="MODBUS_ADD_MISSING_SLAVE_ID",
            message="--slave-id is required when --device-type is given",
            exit_code=ExitCode.USAGE,
        )
    if slave_id in existing_slave_ids:
        return [], [slave_id], []

    warnings: list = []
    template = find_template(device_type)
    if template is None:
        warnings.append(
            f"Template for '{device_type}' not found — required parameters not filled. "
            "Validate the config manually after adding."
        )
    device = {"device_type": device_type, "slave_id": slave_id, "enabled": True}
    if template:
        for param_id, default in required_params_from_template(template).items():
            device.setdefault(param_id, default)
    target_port.setdefault("devices", []).append(device)
    return [{"slave_id": slave_id, "device_type": device_type}], [], warnings


# --------------------------------------------------------------------------- #
# Modes 2 & 3: from scan results (explicit or cached state)
# --------------------------------------------------------------------------- #


def _add_from_scan(  # pylint: disable=too-many-arguments,too-many-locals
    ctx,
    target_port: dict,
    existing_slave_ids: set,
    scan_devices: list,
    *,
    port_path: str,
) -> tuple[list, list, list]:
    added: list = []
    skipped: list = []
    warnings: list = []

    # Filter to the target port.
    scan_devices = [d for d in scan_devices if d.get("port", {}).get("path") == port_path]
    all_used_ids: set = {
        d.get("cfg", {}).get("slave_id") for d in scan_devices if d.get("cfg", {}).get("slave_id")
    } | existing_slave_ids

    # Pre-pass: resolve physical bus collisions (two scan entries on the same
    # slave_id). Fast Modbus by SN is required — standard write would hit both.
    seen_ids: set = set()
    for dev in scan_devices:
        sid = dev.get("cfg", {}).get("slave_id")
        if sid is None:
            continue
        if sid in seen_ids:
            if not _reassign_slave_id(ctx, dev, all_used_ids, warnings, port_path, bus_collision=True):
                dev["cfg"]["slave_id"] = None  # unresolvable — skipped in main loop
        else:
            seen_ids.add(sid)

    for dev in scan_devices:
        entry = _process_one_scan_device(
            ctx,
            target_port,
            existing_slave_ids,
            all_used_ids,
            warnings,
            dev,
            port_path=port_path,
        )
        if entry is None:
            sid = dev.get("cfg", {}).get("slave_id")
            if sid is not None and sid in existing_slave_ids:
                # Already configured (configured_device_type was set).
                if dev.get("configured_device_type") is not None:
                    skipped.append(sid)
        else:
            added.append(entry)

    return added, skipped, warnings


def _process_one_scan_device(  # pylint: disable=too-many-arguments,too-many-return-statements
    ctx,
    target_port: dict,
    existing_slave_ids: set,
    all_used_ids: set,
    warnings: list,
    dev: dict,
    *,
    port_path: str,
):
    """Add one device from a scan entry. Returns the ``added`` row, or None if skipped."""
    cfg = dev.get("cfg", {})
    sid = cfg.get("slave_id")
    if sid is None:
        return None

    if sid in existing_slave_ids:
        # wb-device-manager sets configured_device_type if the entry matched
        # an existing config row → already configured, skip.
        if dev.get("configured_device_type") is not None:
            return None
        # Different physical device at a conflicting address → reassign.
        if not _reassign_slave_id(ctx, dev, all_used_ids, warnings, port_path, bus_collision=False):
            return None
        sid = cfg.get("slave_id")

    baud_changed = _maybe_fix_baud(ctx, dev, target_port, warnings, port_path=port_path)
    if baud_changed is False:  # explicit failure flag — skip this device
        return None

    identifier = dev.get("configured_device_type") or dev.get("device_signature", "")
    template = find_template(identifier)
    if template is None:
        warnings.append(
            f"slave_id={sid}: template for '{identifier}' not found — "
            "required parameters not filled. Validate config manually."
        )
    device_cfg = _transform_scan_device(dev, target_port, template)
    target_port.setdefault("devices", []).append(device_cfg)
    existing_slave_ids.add(sid)
    all_used_ids.add(sid)

    entry = {"slave_id": sid, "device_type": device_cfg["device_type"]}
    if "_old_slave_id" in dev:
        entry["slave_id_changed"] = f"{dev['_old_slave_id']} → {sid}"
    if baud_changed:  # truthy string like "115200 → 9600"
        entry["baud_changed"] = baud_changed
    return entry


def _maybe_fix_baud(ctx, dev: dict, target_port: dict, warnings: list, *, port_path: str):
    """If device baud differs from port baud, switch device via FC6 reg 110.

    Returns:
      * ``None``  — no change needed
      * a string like ``"115200 → 9600"`` — baud changed successfully
      * ``False`` — change failed (device unreachable); caller must skip
    """
    cfg = dev.get("cfg", {})
    dev_baud = cfg.get("baud_rate")
    port_baud = target_port.get("baud_rate", serial_port.DEFAULT_BAUD_RATE)
    if not dev_baud or dev_baud == port_baud:
        return None
    if _change_device_baud(ctx, port_path, cfg.get("slave_id"), cfg, port_baud):
        cfg["baud_rate"] = port_baud
        return f"{dev_baud} → {port_baud}"
    warnings.append(
        f"slave_id={cfg.get('slave_id')}: could not change baud from {dev_baud} to "
        f"{port_baud} — skipping. Check device connectivity."
    )
    return False


def _transform_scan_device(dev: dict, port_config: dict, template: dict | None) -> dict:
    """Convert a wb-device-manager scan entry into a wb-mqtt-serial device config."""
    cfg = dev.get("cfg", {})
    device = {
        "device_type": (template or {}).get("device_type")
        or dev.get("configured_device_type")
        or dev.get("device_signature", ""),
        "slave_id": cfg["slave_id"],
        "enabled": True,
    }
    # Include UART params only when they differ from the port's defaults.
    for key in _INHERITED_UART_KEYS:
        val = cfg.get(key)
        if val is not None and val != port_config.get(key):
            device[key] = val
    if template:
        for param_id, default in required_params_from_template(template).items():
            device.setdefault(param_id, default)
    return device


# --------------------------------------------------------------------------- #
# Bus-side fixups: baud, slave_id collisions
# --------------------------------------------------------------------------- #


def _change_device_baud(ctx, port_path: str, slave_id: int, cfg: dict, to_baud: int) -> bool:
    """Best-effort baud change; treat RPC failure as "device unreachable"."""
    port = serial_port.port_params_from_cfg(port_path, cfg)
    try:
        serial_bus.change_baud(ctx.rpc, port, slave_id, to_baud)
        return True
    except WbCliError:
        return False


def _change_slave_id_by_sn(ctx, port_path: str, sn: int, new_id: int, cfg: dict) -> bool:
    """Best-effort Fast-Modbus-by-SN slave_id change."""
    port = serial_port.port_params_from_cfg(port_path, cfg)
    try:
        serial_bus.change_slave_id_by_sn(ctx.rpc, port, sn, new_id)
        return True
    except WbCliError:
        return False


def _change_slave_id_standard(ctx, port_path: str, old_id: int, new_id: int, cfg: dict) -> bool:
    """Best-effort standard FC6 reg 128 slave_id change."""
    port = serial_port.port_params_from_cfg(port_path, cfg)
    try:
        serial_bus.change_slave_id_standard(ctx.rpc, port, old_id, new_id)
        return True
    except WbCliError:
        return False


def find_free_slave_id(used_ids: set) -> int | None:
    """First slave_id in [1, 247] not present in ``used_ids``."""
    for sid in range(1, 248):
        if sid not in used_ids:
            return sid
    return None


def _reassign_slave_id(  # pylint: disable=too-many-arguments
    ctx, dev: dict, all_used_ids: set, warnings: list, port_path: str, *, bus_collision: bool
) -> bool:
    """Find a free slave_id and change the device's address in place.

    ``bus_collision=True`` — two physical devices share the address. Standard
    Modbus write would hit both: must use Fast Modbus by SN or fail.

    ``bus_collision=False`` — config-only conflict. Standard write is safe as
    a fallback.

    Updates ``dev['cfg']`` in place; records ``dev['_old_slave_id']`` so the
    caller can report the change.
    """
    cfg = dev.get("cfg", {})
    old_id = cfg.get("slave_id")
    new_id = find_free_slave_id(all_used_ids)
    if new_id is None:
        warnings.append(f"slave_id={old_id}: no free address on bus (1–247 exhausted)")
        return False

    ok = False
    sn_raw = dev.get("sn")
    if sn_raw is not None:
        try:
            ok = _change_slave_id_by_sn(ctx, port_path, int(sn_raw), new_id, cfg)
        except (ValueError, TypeError):
            pass
    if not ok and not bus_collision:
        ok = _change_slave_id_standard(ctx, port_path, old_id, new_id, cfg)

    if not ok:
        if bus_collision:
            warnings.append(
                f"slave_id={old_id}: physical address collision, no SN available — "
                "cannot reassign safely. Assign a unique address manually."
            )
        else:
            warnings.append(f"slave_id={old_id}: could not reassign to {new_id}")
        return False

    cfg["slave_id"] = new_id
    dev["_old_slave_id"] = old_id
    all_used_ids.add(new_id)
    return True


# --------------------------------------------------------------------------- #
# Template helpers (small public surface other modules already reach for)
# --------------------------------------------------------------------------- #


def find_template(identifier: str) -> dict | None:
    """Find a template by device_type, falling back to scan-signature match."""
    return templates.find_template(identifier)


def required_params_from_template(template: dict) -> dict:
    """Return ``{param_id: default}`` for every required parameter in ``template``.

    Templates use two parameter formats:

      * list:  ``[{id, required, default, ...}]``
      * dict:  ``{param_id: {required, default, ...}}``
    """
    result = {}
    params = template.get("device", {}).get("parameters", [])
    if isinstance(params, dict):
        items = ((k, v) for k, v in params.items() if isinstance(v, dict))
    else:
        items = ((p.get("id"), p) for p in params if isinstance(p, dict))
    for param_id, param in items:
        if param.get("required") and param_id and param_id not in result and "default" in param:
            result[param_id] = param["default"]
    return result


# --------------------------------------------------------------------------- #
# Config / scan-state loaders
# --------------------------------------------------------------------------- #


def _load_config(ctx) -> dict:
    result = ctx.rpc.call("confed/Editor/Load", {"path": _SERIAL_CONF_PATH})
    return result.get("content", {}) if isinstance(result, dict) else {}


def _load_target_port(content: dict, port_path: str) -> dict:
    ports = content.get("ports", []) if isinstance(content, dict) else []
    for port in ports:
        if port.get("path") == port_path:
            return port
    raise WbCliError(
        code="MODBUS_ADD_PORT_NOT_FOUND",
        message=f"Port '{port_path}' not found in {_SERIAL_CONF_PATH}",
        details={"port": port_path},
        exit_code=ExitCode.DOMAIN,
    )


def _resolve_scan_devices(ctx, scan_results_arg) -> list:
    if scan_results_arg is not None:
        scan_devices = _parse_scan_results_arg(scan_results_arg)
    else:
        scan_devices = _load_cached_scan_devices(ctx)
    if not scan_devices:
        raise WbCliError(
            code="MODBUS_ADD_EMPTY",
            message="No devices in scan results. Run `wb-cli serial wb-scan` first.",
            exit_code=ExitCode.DOMAIN,
        )
    return scan_devices


def _parse_scan_results_arg(raw_str: str) -> list:
    try:
        raw = json.loads(raw_str)
    except json.JSONDecodeError as exc:
        raise WbCliError(
            code="MODBUS_ADD_INVALID_JSON",
            message=f"--scan-results is not valid JSON: {exc}",
            exit_code=ExitCode.USAGE,
        ) from exc
    # Accept both the full envelope ({data: {devices: [...]}}) and a bare list.
    if isinstance(raw, dict):
        return raw.get("data", raw).get("devices", [])
    return raw


def _load_cached_scan_devices(ctx) -> list:
    """Read the retained ``/wb-device-manager/state`` and return its devices list."""
    with ProgressBar("reading last scan state") as pb:
        pb.update(0)
        try:
            msgs = ctx.mqtt.subscribe("/wb-device-manager/state", timeout=3.0)
        except WbCliError as exc:
            if exc.code == "MQTT_TIMEOUT":
                raise _no_scan_state() from exc
            raise
    if not msgs:
        raise _no_scan_state()
    try:
        state = json.loads(msgs[-1][1])
    except json.JSONDecodeError as exc:
        raise WbCliError(
            code="MODBUS_SCAN_STATE_INVALID",
            message=f"wb-device-manager state is not valid JSON: {exc}",
            exit_code=ExitCode.DOMAIN,
        ) from exc
    return state.get("devices", [])


def _no_scan_state() -> WbCliError:
    return WbCliError(
        code="MODBUS_NO_SCAN_STATE",
        message=(
            "No scan results available from wb-device-manager. "
            "Run `wb-cli serial wb-scan` first, then retry."
        ),
        exit_code=ExitCode.DOMAIN,
    )
