"""Stderr-only progress indicators for long-running operations.

JSON envelopes always go to stdout; these indicators write to stderr so they
never corrupt machine-readable output.  When stderr is not a TTY (logs, CI,
pipes) the indicators stay silent.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Optional, TextIO


def _stream() -> TextIO:
    return sys.stderr


def _enabled() -> bool:
    return _stream().isatty()


class Spinner:
    """Background spinner for operations of unknown duration.

    Usage::

        with Spinner("scanning bus"):
            do_work()
    """

    _FRAMES = "|/-\\"

    def __init__(self, label: str, *, interval: float = 0.1) -> None:
        self._label = label
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "Spinner":
        if _enabled():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if _enabled():
            # Clear our line so the JSON envelope appears on a clean row.
            _stream().write("\r\033[2K")
            _stream().flush()

    def _spin(self) -> None:
        i = 0
        while not self._stop.is_set():
            _stream().write(f"\r{self._FRAMES[i % len(self._FRAMES)]} {self._label}")
            _stream().flush()
            i += 1
            self._stop.wait(self._interval)


class ProgressBar:
    """Foreground progress indicator with a known 0-100 percentage.

    Call ``update(percent, suffix)`` as work advances; ``close()`` (or context
    manager exit) clears the line.
    """

    _WIDTH = 30

    def __init__(self, label: str) -> None:
        self._label = label
        self._closed = False

    def __enter__(self) -> "ProgressBar":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def update(self, percent: int, suffix: str = "") -> None:
        if self._closed or not _enabled():
            return
        percent = max(0, min(100, percent))
        filled = int(self._WIDTH * percent / 100)
        bar = "#" * filled + "-" * (self._WIDTH - filled)
        tail = f"  {suffix}" if suffix else ""
        _stream().write(f"\r{self._label} [{bar}] {percent:3d}%{tail}")
        _stream().flush()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if _enabled():
            _stream().write("\r\033[2K")
            _stream().flush()


def countdown(label: str, seconds: float) -> None:
    """Show a count-up timer while sleeping ``seconds``.

    Useful for fixed-duration captures (e.g. ``serial-debug``) where the work
    happens elsewhere and we only need to wait it out.
    """

    if not _enabled():
        time.sleep(seconds)
        return
    start = time.monotonic()
    deadline = start + seconds
    spinner = Spinner._FRAMES  # pylint: disable=protected-access
    i = 0
    while time.monotonic() < deadline:
        elapsed = time.monotonic() - start
        _stream().write(f"\r{spinner[i % len(spinner)]} {label} ({elapsed:0.1f}s / {seconds:0.0f}s)")
        _stream().flush()
        i += 1
        time.sleep(0.1)
    _stream().write("\r\033[2K")
    _stream().flush()
