"""Error paths and core actions of wb_cli.lib.job.JobManager."""

from __future__ import annotations

import os
import time as _time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.job import JobManager


def test_run_creates_artefacts_and_returns_metadata(tmp_path, shell_returning):
    shell = shell_returning(0)
    meta = JobManager(shell, jobs_dir=tmp_path).run("smoke", "echo hi")
    unit = meta["unit"]
    assert unit.startswith("wb-cli-job-smoke-")
    assert meta["label"] == "smoke"
    assert meta["log"].endswith(f"{unit}.log")
    assert (tmp_path / f"{unit}.sh").read_text() == "echo hi"
    assert (tmp_path / f"{unit}.label").read_text() == "smoke"
    cmd = shell.run.call_args.args[0]
    assert cmd[0] == "systemd-run"
    assert f"--unit={unit}" in cmd


def test_run_failure_raises_job_start_failed(tmp_path, shell_returning):
    shell = shell_returning(1, stderr="Unit already exists")
    with pytest.raises(WbCliError) as exc:
        JobManager(shell, jobs_dir=tmp_path).run("dup", "true")
    assert exc.value.code == "JOB_START_FAILED"


def test_status_active(tmp_path, shell_returning):
    (tmp_path / "u.label").write_text("smoke")
    shell = shell_returning(0, "active\n")
    assert JobManager(shell, jobs_dir=tmp_path).status("u") == {
        "unit": "u",
        "label": "smoke",
        "state": "active",
        "log_path": str(tmp_path / "u.log"),
    }


def test_status_failed_unit_returns_failed(shell_returning):
    shell = shell_returning(3, "failed\n")
    st = JobManager(shell, jobs_dir=Path("/nonexistent/dir")).status("u")
    assert st["state"] == "failed"
    assert st["label"] is None


def test_tail_reads_log(tmp_path, shell_returning):
    (tmp_path / "u.log").write_text("line1\nline2\nline3\n")
    shell = shell_returning(0, "line2\nline3\n")
    out = JobManager(shell, jobs_dir=tmp_path).tail("u", lines=2)
    cmd = shell.run.call_args.args[0]
    assert cmd[:2] == ["tail", "-n2"]
    assert out == "line2\nline3\n"


def test_tail_missing_log_raises_job_not_found(tmp_path, shell_returning):
    with pytest.raises(WbCliError) as exc:
        JobManager(shell_returning(0), jobs_dir=tmp_path).tail("missing")
    assert exc.value.code == "JOB_NOT_FOUND"


def test_cancel_active(tmp_path, shell_returning):
    shell = shell_returning(0)
    JobManager(shell, jobs_dir=tmp_path).cancel("u")
    assert shell.run.call_args.args[0] == ["systemctl", "stop", "u"]


def test_cancel_missing_raises_job_not_found(tmp_path, shell_returning):
    shell = shell_returning(5, stderr="Failed to stop u.service: Unit not loaded")
    with pytest.raises(WbCliError) as exc:
        JobManager(shell, jobs_dir=tmp_path).cancel("u")
    assert exc.value.code == "JOB_NOT_FOUND"


def test_wait_returns_status_when_unit_becomes_inactive(tmp_path):
    (tmp_path / "u.label").write_text("smoke")
    shell = MagicMock()
    # is-active: still active; then inactive; then status() lookup.
    shell.run.side_effect = [(0, "", ""), (3, "", ""), (3, "inactive\n", "")]
    with patch("wb_cli.lib.job.time.sleep"):
        st = JobManager(shell, jobs_dir=tmp_path).wait("u", timeout=10.0, poll_interval=0.0)
    assert st["state"] == "inactive"


def test_wait_timeout_raises_job_wait_timeout(tmp_path, shell_returning):
    shell = shell_returning(0)  # always "active"
    with patch("wb_cli.lib.job.time.sleep"), patch(
        "wb_cli.lib.job.time.time", side_effect=[0.0, 100.0, 200.0]
    ):
        with pytest.raises(WbCliError) as exc:
            JobManager(shell, jobs_dir=tmp_path).wait("u", timeout=50.0, poll_interval=0.0)
    assert exc.value.code == "JOB_WAIT_TIMEOUT"


def test_gc_removes_stale_job_files(tmp_path, shell_returning):
    old = tmp_path / "old-job.label"
    fresh = tmp_path / "fresh-job.label"
    old.write_text("old")
    fresh.write_text("fresh")
    past = _time.time() - 48 * 3600
    os.utime(old, (past, past))
    for suffix in (".sh", ".log", ".started"):
        path = tmp_path / f"old-job{suffix}"
        path.write_text("x")
        os.utime(path, (past, past))

    JobManager(shell_returning(0), jobs_dir=tmp_path)._gc()  # pylint: disable=protected-access
    assert not old.exists()
    assert fresh.exists()
