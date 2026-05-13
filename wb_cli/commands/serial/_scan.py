"""``wb-cli serial wb-scan`` — bus scan flow.

Drives ``wb-device-manager/bus-scan/Start``, polls the state topic until the
device-manager declares it done, and aggregates per-port results into the
envelope the user sees.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List

from wb_cli.errors import WbCliError
from wb_cli.lib import serial_port
from wb_cli.lib.progress import ProgressBar

# Tunables. Externalised here so other tests / future tools can adjust them
# without rewriting the scan loop.
BROKER_SETTLE_S = 1.0
SUB_CONNECT_S = 0.5
SCAN_STOP_TIMEOUT_S = 2.0
SCAN_RPC_TIMEOUT_S = 5.0


def scan(ctx) -> dict:
    """Top-level ``wb-cli serial wb-scan`` handler."""
    _try_stop_running_scan(ctx)
    time.sleep(BROKER_SETTLE_S)

    scan_type = ctx.args.scan_type
    ports = ports_to_scan(ctx)
    if not ports:
        return _empty_envelope(scan_type)

    per_port_timeout = ctx.args.timeout if ctx.args.port else max(ctx.args.timeout / len(ports), 5.0)

    aggregate = _Aggregate()
    for port in ports:
        aggregate.add(port, scan_one_port(ctx, port, per_port_timeout))

    return aggregate.envelope(ctx, scan_type)


def scan_one_port(ctx, port: Dict, timeout: float) -> Dict:
    """Run bus-scan/Start for one port; return per-port state."""
    state: Dict = {
        "devices": [],
        "completed": False,
        "progress": 0,
        "received": False,
        "scanning_started": False,
        "error": None,
    }
    with ProgressBar(f"{ctx.args.scan_type} scan of {port['path']}") as progress_bar:
        on_state = _make_state_handler(state, progress_bar)
        try:
            ctx.rpc.call_watch(
                "wb-device-manager/bus-scan/Start",
                {
                    "scan_type": ctx.args.scan_type,
                    "preserve_old_results": False,
                    "port": port,
                },
                state_topic="/wb-device-manager/state",
                skip_retained=True,
                settle_s=SUB_CONNECT_S,
                timeout=timeout,
                on_state=on_state,
                rpc_timeout=SCAN_RPC_TIMEOUT_S,
            )
        finally:
            _try_stop_running_scan(ctx)
    return state


def ports_to_scan(ctx) -> List[Dict]:
    """Resolve which ports this run should scan.

    Source of truth: ``wb-mqtt-serial/ports/Load`` — the active ports the
    driver is currently serving. If the driver dropped a port (schema
    validation), it simply won't be scanned; the user is expected to repair
    the config rather than have wb-cli silently bypass the driver.

    - With ``--port``: filter to that one path; fall back to default UART
      params if the driver doesn't know it (first-time discovery on an
      unconfigured port).
    - Without ``--port``: every port the driver is serving — whatever the
      path looks like. We do NOT exclude ``/dev/ttyMOD*`` here: on most WB
      builds those are cellular modems, but some installs route RS-485
      through MOD-style devices (USB-RS485 adapters, WBE2R add-ons), and
      if the user wired one into ``/etc/wb-mqtt-serial.conf`` and the
      driver opened it, the scan must follow.
    """
    result = ctx.rpc.call("wb-mqtt-serial/ports/Load", {})
    raw_ports = _unwrap_ports(result)
    by_path = {p["path"]: p for p in raw_ports if isinstance(p, dict) and p.get("path")}

    if ctx.args.port:
        return [serial_port.port_params_from_cfg(ctx.args.port, by_path.get(ctx.args.port))]
    return [serial_port.port_params_from_cfg(path, cfg) for path, cfg in by_path.items()]


def _unwrap_ports(result):
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("ports") or []
    return []


def _try_stop_running_scan(ctx) -> None:
    try:
        ctx.rpc.call("wb-device-manager/bus-scan/Stop", {}, timeout=SCAN_STOP_TIMEOUT_S)
    except WbCliError:
        pass


def _empty_envelope(scan_type: str) -> dict:
    return {
        "scan_type": scan_type,
        "devices": [],
        "count": 0,
        "completed": False,
        "hint": (
            "wb-mqtt-serial/ports/Load returned no ports — the driver likely "
            "rejected its config (schema validation). Inspect with "
            "`wb-cli --json confed load /etc/wb-mqtt-serial.conf` and the journal "
            "(`journalctl -u wb-mqtt-serial`); repair the offending stanza via "
            "`wb-cli confed save`. Or pass --port /dev/ttyRS485-N to scan one "
            "specific port without enumerating."
        ),
    }


def _make_state_handler(state: Dict, progress_bar: ProgressBar):
    """Build the ``on_state`` callback for ``rpc.call_watch``.

    The closure mutates ``state`` so the outer loop can read final results
    after the watcher exits.
    """

    def on_state(payload: str) -> bool:
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError:
            return False
        if msg.get("error"):
            # wb-device-manager surfaces per-port failures as ``error`` on the
            # state message. Record and stop the wait, but don't raise —
            # other ports may still succeed.
            state["error"] = msg["error"]
            state["received"] = True
            return True

        is_ext = msg.get("is_ext_scan", False)
        scanning = msg.get("scanning", False)
        new_devices = msg.get("devices", [])
        new_progress = msg.get("progress", 0)

        # wb-device-manager publishes a "reset" state at the very end of a
        # scan (``scanning=false, progress=0, devices=[]``). If we accept it
        # blindly, the accumulated devices list and progress for the run are
        # wiped right before we declare the scan complete. Keep the previous
        # values when the incoming message is empty / zero — the scan list
        # grows monotonically during a single run.
        if new_devices or not state["devices"]:
            state["devices"] = new_devices
        if new_progress or not state["progress"]:
            state["progress"] = new_progress
        state["received"] = True

        phase = "extended" if is_ext else "standard"
        progress_bar.update(state["progress"], suffix=f"{phase}, {len(state['devices'])} device(s)")
        # wb-device-manager publishes scanning=true while running, then false
        # exactly once when it's done. Treat that transition as completion —
        # progress crosses 100 multiple times during slow scans.
        if scanning:
            state["scanning_started"] = True
        elif state["scanning_started"]:
            state["completed"] = True
            return True
        return False

    return on_state


class _Aggregate:
    """Collects per-port results into the final envelope."""

    def __init__(self) -> None:
        self.devices: list = []
        self.completed_all = True
        self.last_progress = 0
        self.received_any = False
        self.failed_ports: list = []

    def add(self, port: Dict, state: Dict) -> None:
        self.devices.extend(state["devices"])
        self.completed_all = self.completed_all and state["completed"]
        self.last_progress = state["progress"]
        self.received_any = self.received_any or state["received"]
        if state["error"]:
            err = state["error"]
            self.failed_ports.append(
                {
                    "port": port["path"],
                    "message": err.get("message", str(err)) if isinstance(err, dict) else str(err),
                }
            )

    def envelope(self, ctx, scan_type: str) -> Dict:
        completed = self.completed_all and not self.failed_ports
        env: Dict = {
            "scan_type": scan_type,
            "devices": self.devices,
            "count": len(self.devices),
            "completed": completed,
        }
        if self.failed_ports:
            env["failed_ports"] = self.failed_ports
        if not completed:
            env["progress"] = self.last_progress
            env["timeout_seconds"] = ctx.args.timeout
            env["hint"] = self._hint()
            if env["hint"] is None:
                del env["hint"]
        if ctx.args.port:
            env["port"] = ctx.args.port
        if self.devices:
            ports_seen = sorted(
                {d.get("port", {}).get("path") for d in self.devices if d.get("port", {}).get("path")}
            )
            # Always show two forms: the all-ports-at-once command (from
            # 1.4.1: ``add-devices`` without ``--port`` iterates every port
            # the scan touched), and per-port variants for selective adds.
            env["add_hints"] = ["wb-cli serial add-devices"] + [
                f"wb-cli serial add-devices --port {p}" for p in ports_seen
            ]
        return env

    def _hint(self):
        if not self.received_any:
            return (
                "wb-device-manager published no scan state — check that it is running "
                "(`systemctl is-active wb-device-manager`) and try again."
            )
        if not self.failed_ports:
            return (
                "Scan did not finish in time. Re-run with a larger --timeout; "
                "--slow and --bootloader scans typically need several minutes per port."
            )
        return None
