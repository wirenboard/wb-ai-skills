"""Single source of truth: debian/changelog, pyproject.toml, wb_cli.__version__ must agree."""

from __future__ import annotations

import re
from pathlib import Path

import wb_cli

ROOT = Path(__file__).resolve().parent.parent


def _changelog_version() -> str:
    first_line = (ROOT / "debian" / "changelog").read_text(encoding="utf-8").splitlines()[0]
    match = re.match(r"^wb-cli \(([^)]+)\)", first_line)
    assert match, f"unrecognised debian/changelog header: {first_line!r}"
    return match.group(1)


def _pyproject_version() -> str:
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        match = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if match:
            return match.group(1)
    raise AssertionError("pyproject.toml has no top-level version")


def test_versions_agree():
    changelog = _changelog_version()
    pyproject = _pyproject_version()
    assert (
        changelog == pyproject == wb_cli.__version__
    ), (
        "Version drift: "
        f"debian/changelog={changelog}, pyproject.toml={pyproject}, "
        f"wb_cli.__version__={wb_cli.__version__}. "
        "Bump them together."
    )
