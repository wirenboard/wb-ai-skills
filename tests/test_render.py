"""Auto-render behaviour for human-mode output."""

from __future__ import annotations

from wb_cli.render import auto_render, render_error


def test_flat_kv_dict_renders_as_aligned_lines():
    out = auto_render({"serial": "A25NDEMJ", "firmware": "202411261637"})
    assert out == "serial    A25NDEMJ\nfirmware  202411261637"


def test_count_key_is_dropped_from_kv():
    out = auto_render({"value": "1", "type": "switch", "count": 99})
    assert "count" not in out
    assert "value" in out and "type" in out


def test_single_list_of_dicts_renders_as_table():
    out = auto_render(
        {
            "devices": [
                {"id": "wb-mr6c_2", "name": "WB-MR6C 2"},
                {"id": "wb-mr3_3", "name": "WB-MR3 3"},
            ],
            "count": 2,
        }
    )
    lines = out.splitlines()
    assert lines[0].split() == ["id", "name"]
    assert "wb-mr6c_2" in lines[2]
    assert "wb-mr3_3" in lines[3]


def test_empty_list_in_table_yields_no_rows_marker():
    assert auto_render({"devices": [], "count": 0}) == "(no rows)"


def test_nested_dict_falls_through_to_pretty_json():
    out = auto_render({"device": {"id": "x", "name": "y"}})
    assert out.startswith("{")
    assert '"id": "x"' in out


def test_bool_scalar_renders_as_yes_no():
    out = auto_render({"ok": True, "readonly": False})
    assert "yes" in out
    assert "no" in out


def test_render_error_one_or_two_lines():
    assert render_error("X", "boom") == "error [X]: boom"
    assert render_error("X", "boom", hint="try foo") == "error [X]: boom\nhint: try foo"
