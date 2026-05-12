"""Modbus subcommand definitions and dispatch."""

from __future__ import annotations

import argparse
import json
import select
import subprocess
import time

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.lib import serial_conf
from wb_cli.lib.progress import ProgressBar

_BROKER_SETTLE_S = 1.0
_SUB_CONNECT_S = 0.5
_SCAN_STOP_TIMEOUT_S = 2.0
# After progress=100 wb-device-manager may still publish another state with
# more devices (the final tally trickles in). Wait this long for the list to
# stop growing before declaring the scan done.
_FINAL_STABLE_S = 1.5


def register_all(sub: argparse._SubParsersAction) -> None:  # pylint: disable=too-many-statements
    """Register all modbus subcommand parsers."""
    p = sub.add_parser(
        "scan",
        help="scan the RS-485 bus and list every device that answers",
        description=(
            "Runs wb-device-manager's bus scan and returns what answered. Same flow\n"
            "the web UI's three scan buttons trigger.\n"
            "\n"
            "  (default)     web-UI «Поиск устройств». WB Fast Modbus — an extension\n"
            "                of standard Modbus, supported by current WB firmware.\n"
            "                Finds every device on the bus that speaks Fast Modbus\n"
            "                (typically all of them on a modern setup).\n"
            "  --slow        web-UI «Начать медленное сканирование». Classic Modbus\n"
            "                poll over every UART combo (8 baud × 3 parity × 2 stop).\n"
            "                Use when the default Fast Modbus pass misses devices —\n"
            "                older firmware without Fast Modbus, or non-default UART.\n"
            "                Takes minutes; raise --timeout accordingly.\n"
            "  --bootloader  web-UI «Поиск устройств в режиме загрузчика». Looks for\n"
            "                devices stuck after a failed `modbus-fw update`.\n"
            "\n"
            "All three modes pass `preserve_old_results=false` so we get a fresh\n"
            "result instead of the retained cache from the previous scan.\n"
            "--slow and --bootloader are mutually exclusive."
        ),
        epilog=(
            "Examples:\n"
            "  wb-cli modbus scan                                    # default — finds everything\n"
            "  wb-cli modbus scan --slow --timeout 600               # exhaustive poll\n"
            "  wb-cli modbus scan --bootloader --port /dev/ttyRS485-1\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--slow",
        dest="scan_type",
        action="store_const",
        const="standard",
        help="exhaustive UART-combo poll (web UI's «Медленное сканирование»)",
    )
    mode.add_argument(
        "--bootloader",
        dest="scan_type",
        action="store_const",
        const="bootloader",
        help="look for devices in bootloader mode after a failed fw-update",
    )
    p.set_defaults(scan_type="extended")
    p.add_argument(
        "--port",
        default=None,
        help="serial port path; if set, wb-device-manager scans only that port",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="seconds to wait for completion (default: 60; bump for --type extended)",
    )

    p = sub.add_parser(
        "probe",
        help="probe a single Modbus address (assumes 9600-N-8-2)",
        description="Send a single Probe request to one slave address on one port. Uses 9600-N-8-2 defaults.",
    )
    p.add_argument("--port", required=True, help="serial port path, e.g. /dev/ttyRS485-1")
    p.add_argument("--address", type=int, required=True, help="Modbus slave address (1-247)")

    sub.add_parser(
        "templates",
        help="list available wb-mqtt-serial device templates",
        description="Names of every JSON template under /usr/share/wb-mqtt-serial/templates/.",
    )

    p = sub.add_parser(
        "template",
        help="dump one device template (registers, channels, defaults)",
        description="Read a single template file from /usr/share/wb-mqtt-serial/templates/.",
    )
    p.add_argument(
        "template_id",
        help="template file name with or without .json, e.g. `config-wb-mr3`",
    )

    p = sub.add_parser(
        "device-info",
        help="show one configured device from /etc/wb-mqtt-serial.conf",
        description="Look up a configured device by `slave_id` or by string `id`.",
    )
    p.add_argument("device_id", help="numeric slave_id or string id from the serial config")

    p = sub.add_parser(
        "devices",
        help="list every device configured in /etc/wb-mqtt-serial.conf",
        description=(
            "Dump every enabled device from the serial config with its effective UART\n"
            "parameters (port-level defaults overridden by device-level fields)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--port",
        default=None,
        help="filter to a single serial port path",
    )

    sub.add_parser(
        "ports",
        help="list serial ports configured in wb-mqtt-serial",
        description="Read /etc/wb-mqtt-serial.conf and dump every port stanza (path + UART params).",
    )

    p = sub.add_parser(
        "add-devices",
        help="add discovered (or named) devices to the serial config",
        description=(
            "Append entries to the `devices` list of one port in /etc/wb-mqtt-serial.conf.\n"
            "Required template parameters are filled from template defaults automatically,\n"
            "so the config is always valid after adding. Devices already present (same\n"
            "slave_id on the same port) are silently skipped — safe to re-run.\n"
            "\n"
            "Three modes, in order of precedence:\n"
            "\n"
            "  --device-type + --slave-id\n"
            "      Add a single device by model without scanning. Looks up the template\n"
            "      by device_type and fills required parameters from template defaults.\n"
            "      Example: --device-type WB-MAI6 --slave-id 19\n"
            "\n"
            "  --scan-results JSON\n"
            "      Use an explicit JSON list of devices (output of `wb-cli --json modbus\n"
            "      scan` → .data.devices). For scripting and agent use.\n"
            "\n"
            "  (default — no extra flags)\n"
            "      Read the retained wb-device-manager state (result of the last scan).\n"
            "      Run `wb-cli modbus scan` or `wb-cli modbus scan --slow` first, then\n"
            "      call this command. Slow-scan results (third-party devices) are\n"
            "      picked up without re-scanning.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # scan → add (typical workflow)\n"
            "  wb-cli modbus scan\n"
            "  wb-cli modbus add-devices --port /dev/ttyRS485-1\n"
            "\n"
            "  # slow scan for third-party devices, then add\n"
            "  wb-cli modbus scan --slow --timeout 300\n"
            "  wb-cli modbus add-devices --port /dev/ttyRS485-1\n"
            "\n"
            "  # add a single device by model (no scan needed)\n"
            "  wb-cli modbus add-devices --port /dev/ttyRS485-1 --device-type WB-MAI6 --slave-id 19\n"
            "\n"
            "  # agent/scripted use\n"
            "  wb-cli --json modbus add-devices --port /dev/ttyRS485-1\n"
        ),
    )
    p.add_argument("--port", required=True, help="target serial port path (must already exist in the config)")
    p.add_argument(
        "--scan-results",
        default=None,
        help=(
            "explicit JSON list of devices (.data.devices from `wb-cli --json modbus scan`); "
            "if omitted, reads the retained state from the last scan"
        ),
    )
    p.add_argument(
        "--device-type",
        default=None,
        help="device_type from the template (e.g. WB-MAI6); requires --slave-id; skips scanning",
    )
    p.add_argument(
        "--slave-id",
        type=int,
        default=None,
        help="Modbus slave address to assign when using --device-type",
    )


def dispatch(ctx) -> dict:  # pylint: disable=too-many-return-statements
    subcmd = ctx.args.subcmd
    if subcmd == "scan":
        return _scan(ctx)
    if subcmd == "probe":
        return _probe(ctx)
    if subcmd == "templates":
        return _templates(ctx)
    if subcmd == "template":
        return _template(ctx)
    if subcmd == "device-info":
        return _device_info(ctx)
    if subcmd == "devices":
        return _devices(ctx)
    if subcmd == "ports":
        return _ports(ctx)
    if subcmd == "add-devices":
        return _add_devices(ctx)
    return {}


def _open_state_stream():
    """Subscribe to /wb-device-manager/state via mosquitto_sub, drop retained."""
    try:
        return subprocess.Popen(
            ["mosquitto_sub", "-R", "-t", "/wb-device-manager/state", "-F", "%p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except FileNotFoundError as exc:
        raise WbCliError(  # pylint: disable=duplicate-code
            code="MQTT_BROKER_DOWN",
            message="mosquitto_sub not found; is mosquitto-clients installed?",
            exit_code=ExitCode.ENVIRONMENT,
        ) from exc


def _reap(proc) -> None:
    """Terminate a Popen safely with a kill fallback."""
    proc.terminate()
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        proc.kill()


def _await_scan(ctx, proc, progress_bar, scan_type: str):
    """Stream wb-device-manager's scan state until done or timeout.

    Returns ``(devices, completed, progress)`` — ``devices`` is the latest
    snapshot we received, ``completed`` says whether the chosen scan finished
    cleanly, and ``progress`` is the last percentage we saw. Partial finds
    are returned even on timeout so the user keeps what was discovered.

    Once we see the first progress=100 state for the chosen phase we keep
    reading for ``_FINAL_STABLE_S`` more seconds, because wb-device-manager
    sometimes publishes one or two more state messages with more devices
    just after reporting 100%.
    """
    deadline = time.monotonic() + ctx.args.timeout
    # Once we receive any state message after calling bus-scan/Start, we know
    # it is fresh (mosquitto_sub -R already dropped the retained message).
    # So any progress>=100 with the right phase means the scan is done — no
    # need for the old saw_progress guard that broke 0→100 instant completions.
    received_state = False
    devices: list = []
    last_progress = 0
    final_deadline: float = 0.0  # set once we first hit done(); read until it expires
    while time.monotonic() < deadline:
        # Non-blocking peek so _FINAL_STABLE_S can fire even when no new
        # state message arrives.
        ready, _, _ = select.select([proc.stdout], [], [], 0.1)
        if not ready:
            if final_deadline and time.monotonic() >= final_deadline:
                return devices, True, last_progress, received_state
            continue
        line = proc.stdout.readline()
        if not line:
            return devices, final_deadline > 0, last_progress, received_state
        try:
            state = json.loads(line)
        except json.JSONDecodeError:
            continue
        if state.get("error"):
            raise WbCliError(
                code="MODBUS_SCAN_FAILED",
                message=f"Bus scan reported error: {state['error']}",
                details={"port": ctx.args.port, "state": state},
                exit_code=ExitCode.DOMAIN,
            )
        progress = state.get("progress", 0)
        is_ext = state.get("is_ext_scan", False)
        devices = state.get("devices", devices)
        last_progress = progress
        received_state = True
        phase = "extended" if is_ext else "standard"
        progress_bar.update(progress, suffix=f"{phase}, {len(devices)} device(s)")
        if 0 < progress < 100:
            final_deadline = 0.0  # ramp-up overrides any earlier stable window
        if progress >= 100 and received_state and _is_done(scan_type, is_ext):
            # Start the stable-window on first done() if not yet started;
            # extend it on each subsequent matching state so the list of
            # discovered devices keeps growing as long as updates arrive.
            final_deadline = time.monotonic() + _FINAL_STABLE_S
    return devices, final_deadline > 0, last_progress, received_state


def _is_done(scan_type: str, is_ext: bool) -> bool:
    # The phase flag in state messages mirrors the scan_type we requested:
    #   extended (default)  → is_ext_scan=True throughout
    #   standard (--slow)   → is_ext_scan=False throughout
    #   bootloader          → no extended phase, any progress=100 is done
    if scan_type == "extended":
        return is_ext
    if scan_type == "standard":
        return not is_ext
    return True


def _rpc_scan_args(args) -> dict:
    """Map CLI args to wb-device-manager's bus-scan/Start kwargs.

    Always pass `preserve_old_results=false` to drop the retained cache from
    the previous scan — otherwise the first state message we see is stale
    and we exit immediately with whatever the previous scan happened to find.
    """
    out: dict = {
        "scan_type": args.scan_type,
        "preserve_old_results": False,
    }
    if args.port:
        out["port"] = args.port
    return out


def _scan(ctx) -> dict:
    # Cancel any previous scan and let the broker quiesce so we don't pick
    # up its tail state messages.
    try:
        ctx.rpc.call("wb-device-manager/bus-scan/Stop", {}, timeout=_SCAN_STOP_TIMEOUT_S)
    except WbCliError:
        pass
    time.sleep(_BROKER_SETTLE_S)

    scan_type = ctx.args.scan_type
    spinner_label = f"{scan_type} scan of {ctx.args.port}" if ctx.args.port else f"{scan_type} RS-485 scan"
    proc = _open_state_stream()
    devices: list = []
    completed = False
    last_progress = 0
    with proc, ProgressBar(spinner_label) as progress_bar:
        try:
            time.sleep(_SUB_CONNECT_S)
            ctx.rpc.call("wb-device-manager/bus-scan/Start", _rpc_scan_args(ctx.args))
            devices, completed, last_progress, received_state = _await_scan(
                ctx, proc, progress_bar, scan_type
            )
        finally:
            try:
                ctx.rpc.call("wb-device-manager/bus-scan/Stop", {}, timeout=_SCAN_STOP_TIMEOUT_S)
            except WbCliError:
                pass
            _reap(proc)

    envelope: dict = {
        "scan_type": scan_type,
        "devices": devices,
        "count": len(devices),
        "completed": completed,
    }
    if not completed:
        envelope["progress"] = last_progress
        envelope["timeout_seconds"] = ctx.args.timeout
        if not received_state:
            envelope["hint"] = (
                "wb-device-manager published no scan state — it may have no ports to scan. "
                "Check that wb-mqtt-serial is running and its config is valid: "
                "`systemctl is-active wb-mqtt-serial` and `wb-cli --json modbus ports`."
            )
        else:
            envelope["hint"] = (
                "Scan did not finish in time. Re-run with a larger --timeout; "
                "--slow scans typically need several minutes per port."
            )
    if ctx.args.port:
        envelope["port"] = ctx.args.port
    if devices and completed:
        ports_seen = list({d.get("port", {}).get("path") for d in devices if d.get("port", {}).get("path")})
        hint_port = ports_seen[0] if len(ports_seen) == 1 else "<port>"
        envelope["add_hint"] = f"wb-cli modbus add-devices --port {hint_port}"
    return envelope


def _probe(ctx) -> dict:
    params = {
        "path": ctx.args.port,
        "baud_rate": 9600,
        "parity": "N",
        "data_bits": 8,
        "stop_bits": 2,
        "slave_id": ctx.args.address,
    }
    try:
        result = ctx.rpc.call("wb-mqtt-serial/device/Probe", params)
    except WbCliError as exc:
        return {
            "port": ctx.args.port,
            "address": ctx.args.address,
            "found": False,
            "error": exc.message,
        }
    # device/Probe returns `{}` when nothing answers on that address —
    # treat an empty result as "no device", not a successful probe.
    found = bool(result) and bool(result.get("device_signature") or result.get("sn"))
    return {
        "port": ctx.args.port,
        "address": ctx.args.address,
        "found": found,
        "result": result if found else None,
    }


def _templates(ctx) -> dict:
    _, stdout, _ = ctx.shell.run(
        ["find", "/usr/share/wb-mqtt-serial/templates", "-name", "*.json", "-printf", "%f\n"],
        timeout=5.0,
    )
    names = sorted(stdout.strip().splitlines()) if stdout.strip() else []
    return {"templates": names, "count": len(names)}


def _template(ctx) -> dict:
    template_id = ctx.args.template_id
    filename = template_id if template_id.endswith(".json") else f"{template_id}.json"
    rc, stdout, _ = ctx.shell.run(
        ["cat", f"/usr/share/wb-mqtt-serial/templates/{filename}"],
        timeout=5.0,
    )
    if rc != 0:
        raise WbCliError(
            code="MODBUS_TEMPLATE_NOT_FOUND",
            message=f"Template '{template_id}' not found",
            details={"template_id": template_id, "filename": filename},
            exit_code=ExitCode.DOMAIN,
        )
    try:
        template = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise WbCliError(
            code="MODBUS_TEMPLATE_INVALID",
            message=f"Template '{template_id}' is not valid JSON: {exc}",
            details={"template_id": template_id},
            exit_code=ExitCode.DOMAIN,
        ) from exc
    return {"template_id": template_id, "template": template}


def _device_info(ctx) -> dict:
    content = serial_conf.load_config(ctx)
    for dev in serial_conf.iter_devices(content):
        if str(dev["slave_id"]) == str(ctx.args.device_id) or dev["id"] == ctx.args.device_id:
            return {"device": dev}
    raise WbCliError(
        code="MODBUS_DEVICE_NOT_FOUND",
        message=f"Device '{ctx.args.device_id}' not in {serial_conf.CONFIG_PATH}",
        details={"device_id": ctx.args.device_id},
        exit_code=ExitCode.DOMAIN,
    )


def _devices(ctx) -> dict:
    content = serial_conf.load_config(ctx)
    devices = serial_conf.list_devices(content, port=ctx.args.port)
    return {"devices": devices, "count": len(devices)}


def _ports(ctx) -> dict:
    result = ctx.rpc.call("wb-mqtt-serial/ports/Load", {})
    ports = result if isinstance(result, list) else result.get("ports", [])
    return {"ports": ports, "count": len(ports)}


def _find_template(ctx, device_type: str) -> dict | None:
    """Return the template dict for device_type, checking custom dir before packaged."""
    template_dirs = [
        "/etc/wb-mqtt-serial.conf.d/templates",
        "/usr/share/wb-mqtt-serial/templates",
    ]
    for template_dir in template_dirs:
        rc, stdout, _ = ctx.shell.run(
            ["grep", "-rl", f'"device_type": "{device_type}"', template_dir],
            timeout=5.0,
        )
        if rc != 0 or not stdout.strip():
            continue
        first_file = stdout.strip().splitlines()[0]
        rc2, content, _ = ctx.shell.run(["cat", first_file], timeout=3.0)
        if rc2 != 0:
            continue
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
    return None


def _required_params_from_template(template: dict) -> dict:
    """Return {param_id: default_value} for all required parameters in a template."""
    result = {}
    for param in template.get("device", {}).get("parameters", []):
        param_id = param.get("id")
        if param.get("required") and param_id and param_id not in result and "default" in param:
            result[param_id] = param["default"]
    return result


def _transform_scan_device(dev: dict, port_config: dict, template: dict | None) -> dict:
    """Convert a wb-device-manager scan result entry to a wb-mqtt-serial device config."""
    cfg = dev.get("cfg", {})
    device = {
        "device_type": dev.get("configured_device_type", ""),
        "slave_id": cfg["slave_id"],
        "enabled": True,
    }
    # Include UART params only when they differ from the port's defaults.
    for key in ("baud_rate", "parity", "data_bits", "stop_bits"):
        val = cfg.get(key)
        if val is not None and val != port_config.get(key):
            device[key] = val
    # Fill required template parameters with their defaults.
    if template:
        for param_id, default in _required_params_from_template(template).items():
            device.setdefault(param_id, default)
    return device


def _load_cached_scan_devices(ctx) -> list:
    """Read the retained /wb-device-manager/state and return its devices list."""
    with ProgressBar("reading last scan state") as pb:
        pb.update(0)
        rc, stdout, _ = ctx.shell.run(
            ["mosquitto_sub", "-t", "/wb-device-manager/state", "-C", "1", "-W", "3"],
            timeout=5.0,
        )
    if rc != 0 or not stdout.strip():
        raise WbCliError(
            code="MODBUS_NO_SCAN_STATE",
            message=(
                "No scan results available from wb-device-manager. "
                "Run `wb-cli modbus scan` first, then retry."
            ),
            exit_code=ExitCode.DOMAIN,
        )
    try:
        state = json.loads(stdout.strip())
    except json.JSONDecodeError as exc:
        raise WbCliError(
            code="MODBUS_SCAN_STATE_INVALID",
            message=f"wb-device-manager state is not valid JSON: {exc}",
            exit_code=ExitCode.DOMAIN,
        ) from exc
    return state.get("devices", [])


def _load_target_port(ctx, content: dict) -> dict:
    ports = content.get("ports", []) if isinstance(content, dict) else []
    for port in ports:
        if port.get("path") == ctx.args.port:
            return port
    raise WbCliError(
        code="MODBUS_ADD_PORT_NOT_FOUND",
        message=f"Port '{ctx.args.port}' not found in /etc/wb-mqtt-serial.conf",
        details={"port": ctx.args.port},
        exit_code=ExitCode.DOMAIN,
    )


def _add_devices(ctx) -> dict:  # pylint: disable=too-many-branches,too-many-statements,too-many-locals
    device_type = getattr(ctx.args, "device_type", None)
    slave_id = getattr(ctx.args, "slave_id", None)
    scan_results_arg = getattr(ctx.args, "scan_results", None)

    result = ctx.rpc.call("confed/Editor/Load", {"path": "/etc/wb-mqtt-serial.conf"})
    content = result.get("content", {}) if isinstance(result, dict) else {}
    target_port = _load_target_port(ctx, content)
    existing_slave_ids = {d.get("slave_id") for d in target_port.get("devices", [])}

    added = []
    skipped = []
    warnings = []

    if device_type is not None:
        # Mode 1: add a single device by model name, no scan needed.
        if slave_id is None:
            raise WbCliError(
                code="MODBUS_ADD_MISSING_SLAVE_ID",
                message="--slave-id is required when --device-type is given",
                exit_code=ExitCode.USAGE,
            )
        if slave_id in existing_slave_ids:
            skipped.append(slave_id)
        else:
            template = _find_template(ctx, device_type)
            if template is None:
                warnings.append(
                    f"Template for '{device_type}' not found — required parameters not filled. "
                    "Validate the config manually after adding."
                )
            device = {"device_type": device_type, "slave_id": slave_id, "enabled": True}
            if template:
                for param_id, default in _required_params_from_template(template).items():
                    device.setdefault(param_id, default)
            target_port.setdefault("devices", []).append(device)
            added.append({"slave_id": slave_id, "device_type": device_type})
    else:
        # Mode 2: from explicit --scan-results JSON, or Mode 3: from cached state.
        if scan_results_arg is not None:
            try:
                raw = json.loads(scan_results_arg)
            except json.JSONDecodeError as exc:
                raise WbCliError(
                    code="MODBUS_ADD_INVALID_JSON",
                    message=f"--scan-results is not valid JSON: {exc}",
                    exit_code=ExitCode.USAGE,
                ) from exc
            # Accept both the full scan envelope ({data: {devices: [...]}}) and a bare list.
            if isinstance(raw, dict):
                scan_devices = raw.get("data", raw).get("devices", [])
            else:
                scan_devices = raw
        else:
            scan_devices = _load_cached_scan_devices(ctx)

        if not scan_devices:
            raise WbCliError(
                code="MODBUS_ADD_EMPTY",
                message="No devices in scan results. Run `wb-cli modbus scan` first.",
                exit_code=ExitCode.DOMAIN,
            )

        # Filter to the target port.
        scan_devices = [d for d in scan_devices if d.get("port", {}).get("path") == ctx.args.port]

        for dev in scan_devices:
            sid = dev.get("cfg", {}).get("slave_id")
            if sid is None:
                continue
            if sid in existing_slave_ids:
                skipped.append(sid)
                continue
            dev_type = dev.get("configured_device_type", "")
            template = _find_template(ctx, dev_type)
            if template is None:
                warnings.append(
                    f"slave_id={sid}: template for '{dev_type}' not found — "
                    "required parameters not filled. Validate config manually."
                )
            device = _transform_scan_device(dev, target_port, template)
            target_port.setdefault("devices", []).append(device)
            existing_slave_ids.add(sid)
            added.append({"slave_id": sid, "device_type": dev_type})

    if added:
        ctx.rpc.call(
            "confed/Editor/Save",
            {"path": "/etc/wb-mqtt-serial.conf", "content": content},
        )

    result = {
        "port": ctx.args.port,
        "added": added,
        "skipped": skipped,
        "count": len(added),
    }
    if warnings:
        result["warnings"] = warnings
    return result
