"""``wb-cli devices`` — semantic /devices/ view: list, controls, set, inventory."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from wb_cli.errors import ExitCode, WbCliError
from wb_cli.plugin import BasePlugin


class DevicesPlugin(BasePlugin):
    name = "devices"
    help = "devices on the controller: list, controls, set values, inventory"

    def register(self, subparsers: argparse._SubParsersAction) -> None:
        parser = subparsers.add_parser(
            self.name,
            help=self.help,
            description="Semantic view of /devices/ topics.",
        )
        sub = parser.add_subparsers(dest="subcmd", metavar="<action>")

        p = sub.add_parser("list", help="list all devices")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("controls", help="list controls with types and values")
        p.add_argument("device", help="device id")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("set", help="set a control value (turn on/off, write)")
        p.add_argument("device", help="device id")
        p.add_argument("control", help="control name")
        p.add_argument("value", help="value to set")
        p.add_argument("-q", "--quiet", action="store_true")

        p = sub.add_parser("inventory", help="full device inventory with metadata")
        p.add_argument("-q", "--quiet", action="store_true")

    def dispatch(self, ctx) -> dict:  # pylint: disable=too-many-return-statements
        subcmd = ctx.args.subcmd
        if subcmd == "list":
            return self._list_devices(ctx)
        if subcmd == "controls":
            return self._controls(ctx)
        if subcmd == "set":
            return self._set(ctx)
        if subcmd == "inventory":
            return self._inventory(ctx)
        return {}

    def _list_devices(self, ctx) -> dict:
        meta = ctx.mqtt.subscribe("/devices/+/meta/+", timeout=5.0)
        devices = _build_device_list(meta)
        return {"devices": devices, "count": len(devices)}

    def _controls(self, ctx) -> dict:
        device = ctx.args.device
        vals = ctx.mqtt.subscribe(f"/devices/{device}/controls/+", timeout=5.0)
        metas = ctx.mqtt.subscribe(f"/devices/{device}/controls/+/meta/+", timeout=5.0)
        if not vals:
            raise WbCliError(
                code="DEVICES_DEVICE_NOT_FOUND",
                message=f"Device '{device}' not found",
                details={"device": device},
                exit_code=ExitCode.DOMAIN,
            )
        controls = _build_controls(vals, metas)
        return {"device": device, "controls": controls, "count": len(controls)}

    def _set(self, ctx) -> dict:
        device = ctx.args.device
        control = ctx.args.control
        value = ctx.args.value
        topic = f"/devices/{device}/controls/{control}/on"
        ctx.mqtt.publish(topic, value)
        return {
            "device": device,
            "control": control,
            "value": value,
            "ok": True,
        }

    def _inventory(self, ctx) -> dict:
        dev_meta = ctx.mqtt.subscribe("/devices/+/meta/+", timeout=5.0)
        ctrl_vals = ctx.mqtt.subscribe("/devices/+/controls/+", timeout=5.0)
        ctrl_meta = ctx.mqtt.subscribe("/devices/+/controls/+/meta/+", timeout=5.0)
        devices = _build_inventory(dev_meta, ctrl_vals, ctrl_meta)
        return {"devices": devices, "count": len(devices)}


def _build_device_list(meta_msgs: List[tuple]) -> List[Dict[str, Any]]:
    """Build device list from /devices/+/meta/+ messages."""
    devs: Dict[str, Dict[str, Any]] = {}
    for topic, payload in meta_msgs:
        parts = topic.split("/")
        if len(parts) < 5:
            continue
        dev_id = parts[2]
        meta_key = parts[4]
        devs.setdefault(dev_id, {"id": dev_id})
        devs[dev_id][meta_key] = payload
    return sorted(devs.values(), key=lambda d: d["id"])


def _build_controls(
    vals: List[tuple],
    metas: List[tuple],
) -> List[Dict[str, Any]]:
    """Build control list with values, types, readonly, errors."""
    ctrls: Dict[str, Dict[str, Any]] = {}
    for topic, payload in vals:
        name = _control_name_from_value_topic(topic)
        ctrls.setdefault(name, {"name": name})
        ctrls[name]["value"] = payload

    for topic, payload in metas:
        parts = topic.split("/")
        if len(parts) < 7:
            continue
        name = parts[4]
        meta_key = parts[6]
        ctrls.setdefault(name, {"name": name})
        if meta_key == "type":
            ctrls[name]["type"] = payload
        elif meta_key == "readonly":
            ctrls[name]["readonly"] = payload == "1"
        elif meta_key == "error":
            ctrls[name]["error"] = _parse_error_flags(payload)
        elif meta_key == "order":
            ctrls[name]["order"] = int(payload) if payload.isdigit() else 0

    result = sorted(ctrls.values(), key=lambda c: c.get("order", 999))
    for ctrl in result:
        ctrl.pop("order", None)
        ctrl.setdefault("type", None)
        ctrl.setdefault("readonly", False)
        ctrl.setdefault("error", None)
    return result


def _build_inventory(
    dev_meta: List[tuple],
    ctrl_vals: List[tuple],
    ctrl_meta: List[tuple],
) -> List[Dict[str, Any]]:
    """Full inventory: devices with controls, types, errors."""
    devs: Dict[str, Dict[str, Any]] = {}
    for topic, payload in dev_meta:
        parts = topic.split("/")
        if len(parts) < 5:
            continue
        dev_id, meta_key = parts[2], parts[4]
        devs.setdefault(dev_id, {"id": dev_id, "meta": {}, "controls": {}})
        devs[dev_id]["meta"][meta_key] = payload

    for topic, payload in ctrl_vals:
        parts = topic.split("/")
        if len(parts) < 5:
            continue
        dev_id, ctrl_name = parts[2], parts[4]
        devs.setdefault(dev_id, {"id": dev_id, "meta": {}, "controls": {}})
        devs[dev_id]["controls"].setdefault(ctrl_name, {"name": ctrl_name})
        devs[dev_id]["controls"][ctrl_name]["value"] = payload

    for topic, payload in ctrl_meta:
        parts = topic.split("/")
        if len(parts) < 7:
            continue
        dev_id, ctrl_name, meta_key = parts[2], parts[4], parts[6]
        devs.setdefault(dev_id, {"id": dev_id, "meta": {}, "controls": {}})
        devs[dev_id]["controls"].setdefault(ctrl_name, {"name": ctrl_name})
        devs[dev_id]["controls"][ctrl_name][meta_key] = payload

    result = []
    for dev in sorted(devs.values(), key=lambda d: d["id"]):
        dev["controls"] = list(dev["controls"].values())
        result.append(dev)
    return result


def _control_name_from_value_topic(topic: str) -> str:
    parts = topic.split("/")
    return parts[4] if len(parts) >= 5 else topic


def _parse_error_flags(payload: str) -> Dict[str, bool]:
    """Parse error flags like 'r' or 'rw' or 'p' into structured dict."""
    return {
        "read": "r" in payload,
        "write": "w" in payload,
        "period_miss": "p" in payload,
    }


PLUGIN = DevicesPlugin()
