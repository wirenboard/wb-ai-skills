"""Read controller identity and basic system info from local files.

Real paths on a Wiren Board 7::

    /etc/wb-release                      RELEASE_NAME, SUITE, TARGET
    /var/lib/wirenboard/short_sn.conf    serial number (one line)
    /etc/wb-fw-version                   firmware build timestamp
    /etc/hostname                        hostname (one line)
    /proc/uptime                         two floats: uptime_sec idle_sec
    /proc/device-tree/wirenboard/        board-revision, dram-size, ...

The ``root`` parameter shifts every path so tests can point at a fixture tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

_DEFAULT_ROOT = Path("/")

# Paths relative to root
_WB_RELEASE = "etc/wb-release"
_SHORT_SN = "var/lib/wirenboard/short_sn.conf"
_FW_VERSION = "etc/wb-fw-version"
_HOSTNAME = "etc/hostname"
_UPTIME = "proc/uptime"
_DEVICE_TREE = "proc/device-tree/wirenboard"


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return None


def _parse_wb_release(text: Optional[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not text:
        return result
    for line in text.splitlines():
        line = line.strip()
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _parse_uptime(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    try:
        return float(text.split()[0])
    except (ValueError, IndexError):
        return None


def _read_device_tree(dt_dir: Path) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {}
    if not dt_dir.is_dir():
        return result
    for entry in sorted(dt_dir.iterdir()):
        if entry.is_file():
            raw = _read_text(entry)
            if raw is not None:
                raw = raw.rstrip("\x00")
            result[entry.name] = raw
    return result


@dataclass
class ControllerInfo:  # pylint: disable=too-many-instance-attributes
    """Lazily loaded controller identity and basic system facts."""

    root: Path = field(default=_DEFAULT_ROOT, repr=False)

    _loaded: bool = field(default=False, init=False, repr=False)
    _serial_number: Optional[str] = field(default=None, init=False, repr=False)
    _release_name: Optional[str] = field(default=None, init=False, repr=False)
    _suite: Optional[str] = field(default=None, init=False, repr=False)
    _target: Optional[str] = field(default=None, init=False, repr=False)
    _fw_version: Optional[str] = field(default=None, init=False, repr=False)
    _hostname: Optional[str] = field(default=None, init=False, repr=False)
    _uptime_seconds: Optional[float] = field(default=None, init=False, repr=False)
    _device_tree: Dict[str, Optional[str]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        wb_rel = _parse_wb_release(_read_text(self.root / _WB_RELEASE))
        self._release_name = wb_rel.get("RELEASE_NAME")
        self._suite = wb_rel.get("SUITE")
        self._target = wb_rel.get("TARGET")

        self._serial_number = _read_text(self.root / _SHORT_SN)
        self._fw_version = _read_text(self.root / _FW_VERSION)
        self._hostname = _read_text(self.root / _HOSTNAME)
        self._uptime_seconds = _parse_uptime(
            _read_text(self.root / _UPTIME),
        )
        self._device_tree = _read_device_tree(self.root / _DEVICE_TREE)

        self._loaded = True

    @property
    def serial_number(self) -> Optional[str]:
        self._ensure_loaded()
        return self._serial_number

    @property
    def release_name(self) -> Optional[str]:
        self._ensure_loaded()
        return self._release_name

    @property
    def suite(self) -> Optional[str]:
        self._ensure_loaded()
        return self._suite

    @property
    def target(self) -> Optional[str]:
        self._ensure_loaded()
        return self._target

    @property
    def fw_version(self) -> Optional[str]:
        self._ensure_loaded()
        return self._fw_version

    @property
    def hostname(self) -> Optional[str]:
        self._ensure_loaded()
        return self._hostname

    @property
    def uptime_seconds(self) -> Optional[float]:
        self._ensure_loaded()
        return self._uptime_seconds

    @property
    def device_tree(self) -> Dict[str, Optional[str]]:
        self._ensure_loaded()
        return dict(self._device_tree)

    def to_dict(self) -> dict:
        """Return all fields as a dict suitable for the JSON envelope."""
        self._ensure_loaded()
        return {
            "serial_number": self._serial_number,
            "release_name": self._release_name,
            "suite": self._suite,
            "target": self._target,
            "hostname": self._hostname,
            "uptime_seconds": self._uptime_seconds,
            "device_tree": dict(self._device_tree),
        }
