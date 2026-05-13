"""Tests for ``wb_cli.lib.templates`` (filesystem template lookup)."""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import json
from pathlib import Path

import pytest
from wb_cli.lib import templates


@pytest.fixture()
def two_dirs(tmp_path: Path):
    custom = tmp_path / "custom"
    packaged = tmp_path / "packaged"
    custom.mkdir()
    packaged.mkdir()
    return custom, packaged


def test_list_template_names_dedup_across_dirs(two_dirs):
    custom, packaged = two_dirs
    (custom / "wb-mr6c.json").write_text("{}", encoding="utf-8")
    (packaged / "wb-mr6c.json").write_text("{}", encoding="utf-8")
    (packaged / "wb-msw-v4.json").write_text("{}", encoding="utf-8")
    names = templates.list_template_names((custom, packaged))
    assert names == ["wb-mr6c.json", "wb-msw-v4.json"]


def test_read_template_custom_overrides_packaged(two_dirs):
    custom, packaged = two_dirs
    (custom / "wb-mr6c.json").write_text(json.dumps({"src": "custom"}), encoding="utf-8")
    (packaged / "wb-mr6c.json").write_text(json.dumps({"src": "packaged"}), encoding="utf-8")
    template = templates.read_template("wb-mr6c", (custom, packaged))
    assert template == {"src": "custom"}


def test_read_template_missing_returns_none(two_dirs):
    custom, packaged = two_dirs
    assert templates.read_template("nope", (custom, packaged)) is None


def test_read_template_accepts_id_with_suffix(two_dirs):
    custom, _ = two_dirs
    (custom / "x.json").write_text(json.dumps({"k": 1}), encoding="utf-8")
    assert templates.read_template("x.json", (custom,)) == {"k": 1}
    assert templates.read_template("x", (custom,)) == {"k": 1}


def test_read_template_propagates_invalid_json(two_dirs):
    custom, _ = two_dirs
    (custom / "broken.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        templates.read_template("broken", (custom,))


def test_find_template_by_device_type(two_dirs):
    custom, packaged = two_dirs
    (packaged / "config-wb-mai6.json").write_text(json.dumps({"device_type": "WB-MAI6"}), encoding="utf-8")
    template = templates.find_template("WB-MAI6", (custom, packaged))
    assert template == {"device_type": "WB-MAI6"}


def test_find_template_by_signature_fallback(two_dirs):
    custom, packaged = two_dirs
    (packaged / "wb-mr6c.json").write_text(
        json.dumps({"device_type": "WB-MR6C", "signature": "WBMR6C"}), encoding="utf-8"
    )
    template = templates.find_template("WBMR6C", (custom, packaged))
    assert template is not None
    assert template["device_type"] == "WB-MR6C"


def test_find_template_skips_deprecated_when_better_exists(two_dirs):
    _, packaged = two_dirs
    deprecated_dir = packaged / "deprecated"
    deprecated_dir.mkdir()
    (deprecated_dir / "old.json").write_text(json.dumps({"device_type": "X", "tag": "old"}), encoding="utf-8")
    (packaged / "new.json").write_text(json.dumps({"device_type": "X", "tag": "new"}), encoding="utf-8")
    # only top-level files are scanned, deprecated subdir is ignored entirely
    template = templates.find_template("X", (packaged,))
    assert template == {"device_type": "X", "tag": "new"}


def test_find_template_unknown_returns_none(two_dirs):
    custom, _ = two_dirs
    assert templates.find_template("UNKNOWN", (custom,)) is None
