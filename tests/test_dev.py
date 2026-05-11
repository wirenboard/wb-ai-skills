"""``wb-cli dev`` — quick get/set over <device>/<control> addressing.

Important edge case: WB control names routinely contain spaces
(``Channel 1 Dimming Level``, ``Current uptime``). The plugin must treat the
*first* ``/`` as the device-name separator and keep everything after as the
control name verbatim — spaces and all.
"""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock

import pytest
from wb_cli.commands.dev import DevPlugin
from wb_cli.context import CliContext
from wb_cli.errors import WbCliError


def _ctx(address=None, value=None, *, show_all=False):
    args = argparse.Namespace(address=address, value=value, show_all=show_all, quiet=False)
    ctx = CliContext(args, quiet=False)
    ctx._mqtt = MagicMock()  # pylint: disable=protected-access
    return ctx


# ---------- list (no args) ----------


# ---------- list (no args) — full table with meta ----------


def test_list_returns_full_columns():
    ctx = _ctx()
    ctx.mqtt.subscribe.side_effect = [
        [
            ("/devices/wb-mr6c_2/controls/K1", "1"),
            ("/devices/wb-mr6c_2/controls/Input 0", "0"),
        ],
        [
            ("/devices/wb-mr6c_2/controls/K1/meta/type", "switch"),
            ("/devices/wb-mr6c_2/controls/K1/meta/readonly", "0"),
            ("/devices/wb-mr6c_2/controls/Input 0/meta/type", "switch"),
            ("/devices/wb-mr6c_2/controls/Input 0/meta/readonly", "1"),
        ],
    ]
    result = DevPlugin().dispatch(ctx)
    assert result["count"] == 2
    k1 = next(c for c in result["controls"] if c["control"] == "K1")
    assert k1 == {
        "device": "wb-mr6c_2",
        "control": "K1",
        "value": "1",
        "type": "switch",
        "readonly": False,
        "error": None,
    }
    inp = next(c for c in result["controls"] if c["control"] == "Input 0")
    assert inp["readonly"] is True


def test_list_render_emits_table_with_header():
    ctx = _ctx()
    ctx.mqtt.subscribe.side_effect = [
        [("/devices/wb-mr6c_2/controls/K1", "1")],
        [("/devices/wb-mr6c_2/controls/K1/meta/type", "switch")],
    ]
    result = DevPlugin().dispatch(ctx)
    out = DevPlugin().render(result)
    lines = out.splitlines()
    # Compact 3-column layout (error column hidden when no row has errors).
    assert lines[0].split() == ["address", "value", "type"]
    assert "wb-mr6c_2/K1" in lines[2]
    # type column merges readonly flag: `switch/rw` / `switch/ro`
    assert "switch/rw" in lines[2]
    assert "switch" in lines[2]


def test_list_filters_system_by_default():
    ctx = _ctx()
    ctx.mqtt.subscribe.side_effect = [
        [
            ("/devices/system_time/controls/now", "12:00"),
            ("/devices/wb-mr6c_2/controls/K1", "1"),
        ],
        [],
    ]
    result = DevPlugin().dispatch(ctx)
    devs = {c["device"] for c in result["controls"]}
    assert devs == {"wb-mr6c_2"}


def test_list_all_includes_system():
    ctx = _ctx(show_all=True)
    ctx.mqtt.subscribe.side_effect = [
        [
            ("/devices/system_time/controls/now", "12:00"),
            ("/devices/wb-mr6c_2/controls/K1", "1"),
        ],
        [],
    ]
    result = DevPlugin().dispatch(ctx)
    devs = {c["device"] for c in result["controls"]}
    assert devs == {"system_time", "wb-mr6c_2"}


# ---------- single device controls ----------


def test_bare_device_returns_its_controls():
    ctx = _ctx("wb-mr6c_2")
    ctx.mqtt.subscribe.side_effect = [
        [
            ("/devices/wb-mr6c_2/controls/K1", "1"),
            ("/devices/wb-mr6c_2/controls/K2", "0"),
        ],
        [
            ("/devices/wb-mr6c_2/controls/K1/meta/type", "switch"),
            ("/devices/wb-mr6c_2/controls/K2/meta/type", "switch"),
        ],
    ]
    result = DevPlugin().dispatch(ctx)
    assert result["device"] == "wb-mr6c_2"
    assert result["count"] == 2
    out = DevPlugin().render(result)
    # device column collapsed since the whole table is one device
    assert "wb-mr6c_2" not in out.splitlines()[0]


def test_bare_device_missing_raises_device_not_found():
    ctx = _ctx("wb-nope")
    ctx.mqtt.subscribe.return_value = []
    with pytest.raises(WbCliError) as exc:
        DevPlugin().dispatch(ctx)
    assert exc.value.code == "DEV_DEVICE_NOT_FOUND"


def test_bare_device_with_value_is_usage_error():
    """`wb-cli dev wb-mr6c_2 1` is ambiguous — refuse."""
    ctx = _ctx("wb-mr6c_2", value="1")
    with pytest.raises(WbCliError) as exc:
        DevPlugin().dispatch(ctx)
    assert exc.value.code == "DEV_INVALID_ADDRESS"


# ---------- get ----------


def test_get_returns_value_and_meta():
    ctx = _ctx("wb-mr6c_2/K1")
    ctx.mqtt.subscribe.side_effect = [
        [("/devices/wb-mr6c_2/controls/K1", "1")],
        [
            ("/devices/wb-mr6c_2/controls/K1/meta/type", "switch"),
            ("/devices/wb-mr6c_2/controls/K1/meta/readonly", "0"),
        ],
    ]
    result = DevPlugin().dispatch(ctx)
    assert result == {
        "device": "wb-mr6c_2",
        "control": "K1",
        "value": "1",
        "type": "switch",
        "readonly": False,
    }


def test_get_handles_spaces_in_control_name():
    ctx = _ctx("wb-mdm3_5/Channel 1 Dimming Level")
    ctx.mqtt.subscribe.side_effect = [
        [("/devices/wb-mdm3_5/controls/Channel 1 Dimming Level", "30")],
        [("/devices/wb-mdm3_5/controls/Channel 1 Dimming Level/meta/type", "range")],
    ]
    result = DevPlugin().dispatch(ctx)
    assert result["control"] == "Channel 1 Dimming Level"
    assert result["value"] == "30"
    # subscribe must have been called with the literal control path, spaces and all
    call_topic = ctx.mqtt.subscribe.call_args_list[0].args[0]
    assert call_topic == "/devices/wb-mdm3_5/controls/Channel 1 Dimming Level"


def test_get_missing_control():
    ctx = _ctx("wb-mr6c_2/nope")
    ctx.mqtt.subscribe.return_value = []
    with pytest.raises(WbCliError) as exc:
        DevPlugin().dispatch(ctx)
    assert exc.value.code == "DEV_CONTROL_NOT_FOUND"


# ---------- set ----------


def test_set_publishes_to_on_topic():
    ctx = _ctx("wb-mr6c_2/K1", value="1")
    ctx.mqtt.subscribe.side_effect = [
        [("/devices/wb-mr6c_2/controls/K1", "0")],
        [("/devices/wb-mr6c_2/controls/K1/meta/type", "switch")],
    ]
    result = DevPlugin().dispatch(ctx)
    assert result["ok"] is True
    ctx.mqtt.publish.assert_called_once_with("/devices/wb-mr6c_2/controls/K1/on", "1")


def test_set_handles_spaces_in_control_and_value():
    ctx = _ctx("wb-mdm3_5/Channel 1 Dimming Level", value="40")
    ctx.mqtt.subscribe.side_effect = [
        [("/devices/wb-mdm3_5/controls/Channel 1 Dimming Level", "30")],
        [("/devices/wb-mdm3_5/controls/Channel 1 Dimming Level/meta/type", "range")],
    ]
    DevPlugin().dispatch(ctx)
    ctx.mqtt.publish.assert_called_once_with(
        "/devices/wb-mdm3_5/controls/Channel 1 Dimming Level/on",
        "40",
    )


def test_set_accepts_value_with_spaces():
    ctx = _ctx("custom-dev/mode", value="auto night")
    ctx.mqtt.subscribe.side_effect = [
        [("/devices/custom-dev/controls/mode", "day")],
        [("/devices/custom-dev/controls/mode/meta/type", "text")],
    ]
    DevPlugin().dispatch(ctx)
    ctx.mqtt.publish.assert_called_once_with(
        "/devices/custom-dev/controls/mode/on",
        "auto night",
    )


def test_set_refuses_unknown_control():
    ctx = _ctx("wb-fake/X", value="1")
    ctx.mqtt.subscribe.return_value = []
    with pytest.raises(WbCliError) as exc:
        DevPlugin().dispatch(ctx)
    assert exc.value.code == "DEV_CONTROL_NOT_FOUND"
    ctx.mqtt.publish.assert_not_called()


def test_set_refuses_readonly_control():
    ctx = _ctx("wb-gpio/D1_IN", value="1")
    ctx.mqtt.subscribe.side_effect = [
        [("/devices/wb-gpio/controls/D1_IN", "0")],
        [
            ("/devices/wb-gpio/controls/D1_IN/meta/type", "switch"),
            ("/devices/wb-gpio/controls/D1_IN/meta/readonly", "1"),
        ],
    ]
    with pytest.raises(WbCliError) as exc:
        DevPlugin().dispatch(ctx)
    assert exc.value.code == "DEV_CONTROL_READONLY"
    ctx.mqtt.publish.assert_not_called()


# ---------- address parsing ----------


def test_address_with_empty_device_or_control_is_usage_error():
    for bad in ("/K1", "wb-mr6c_2/"):
        ctx = _ctx(bad)
        # Both have a slash, so the get/set branch parses them and rejects.
        # First triggers subscribe for the empty parts; second has empty
        # control after the slash. We probe each path explicitly.
        ctx.mqtt.subscribe.return_value = []
        with pytest.raises(WbCliError) as exc:
            DevPlugin().dispatch(ctx)
        assert exc.value.code in {"DEV_INVALID_ADDRESS", "DEV_CONTROL_NOT_FOUND", "DEV_DEVICE_NOT_FOUND"}


# ---------- render ----------


def test_render_get_value_with_flags():
    out = DevPlugin().render(
        {"device": "wb-mr6c_2", "control": "K1", "value": "1", "type": "switch", "readonly": False}
    )
    assert out == "1  (switch, rw)"


def test_render_set_ok_line():
    out = DevPlugin().render({"device": "wb-mr6c_2", "control": "K1", "value": "1", "ok": True})
    assert out == "ok  wb-mr6c_2/K1 := 1"
