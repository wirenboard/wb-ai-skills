"""Error paths and core actions of wb_cli.lib.job.JobManager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.job import JobManager


def _shell(rc=0, stdout="", stderr=""):
    shell = MagicMock()
    shell.run.return_value = (rc, stdout, stderr)
    return shell


def test_run_creates_artefacts_and_returns_metadata(tmp_path):
    shell = _shell()
    mgr = JobManager(shell, jobs_dir=tmp_path)
    meta = mgr.run("smoke", "echo hi")
    unit = meta["unit"]
    assert unit.startswith("wb-cli-job-smoke-")
    assert meta["label"] == "smoke"
    assert meta["log"].endswith(f"{unit}.log")
    assert (tmp_path / f"{unit}.sh").read_text() == "echo hi"
    assert (tmp_path / f"{unit}.label").read_text() == "smoke"
    cmd = shell.run.call_args.args[0]
    assert cmd[0] == "systemd-run"
    assert f"--unit={unit}" in cmd


def test_run_failure_raises_job_already_running(tmp_path):
    shell = _shell(rc=1, stderr="Unit already exists")
    with pytest.raises(WbCliError) as exc:
        JobManager(shell, jobs_dir=tmp_path).run("dup", "true")
    assert exc.value.code == "JOB_ALREADY_RUNNING"


def test_status_active(tmp_path):
    (tmp_path / "u.label").write_text("smoke")
    shell = _shell(rc=0, stdout="active\n")
    st = JobManager(shell, jobs_dir=tmp_path).status("u")
    assert st == {
        "unit": "u",
        "label": "smoke",
        "state": "active",
        "log_path": str(tmp_path / "u.log"),
    }


def test_status_missing_label_returns_none():
    shell = _shell(rc=3, stdout="failed\n")
    st = JobManager(shell, jobs_dir=Path("/nonexistent/dir")).status("u")
    assert st["state"] == "inactive"
    assert st["label"] is None


def test_tail_reads_log(tmp_path):
    (tmp_path / "u.log").write_text("line1\nline2\nline3\n")
    shell = _shell(rc=0, stdout="line2\nline3\n")
    out = JobManager(shell, jobs_dir=tmp_path).tail("u", lines=2)
    cmd = shell.run.call_args.args[0]
    assert cmd[:2] == ["tail", "-n2"]
    assert out == "line2\nline3\n"


def test_tail_missing_log_raises_job_not_found(tmp_path):
    with pytest.raises(WbCliError) as exc:
        JobManager(_shell(), jobs_dir=tmp_path).tail("missing")
    assert exc.value.code == "JOB_NOT_FOUND"


def test_cancel_active(tmp_path):
    shell = _shell()
    JobManager(shell, jobs_dir=tmp_path).cancel("u")
    cmd = shell.run.call_args.args[0]
    assert cmd == ["systemctl", "stop", "u"]


def test_cancel_missing_raises_job_not_found(tmp_path):
    shell = _shell(rc=5, stderr="Failed to stop u.service: Unit not loaded")
    with pytest.raises(WbCliError) as exc:
        JobManager(shell, jobs_dir=tmp_path).cancel("u")
    assert exc.value.code == "JOB_NOT_FOUND"


def test_wait_returns_status_when_unit_becomes_inactive(tmp_path):
    (tmp_path / "u.label").write_text("smoke")
    shell = MagicMock()
    # First is-active: rc=0 (still active); second: rc=3 (inactive);
    # then the .status() call: rc=3, stdout="inactive\n".
    shell.run.side_effect = [
        (0, "", ""),
        (3, "", ""),
        (3, "inactive\n", ""),
    ]
    with patch("wb_cli.lib.job.time.sleep"):
        st = JobManager(shell, jobs_dir=tmp_path).wait("u", timeout=10.0, poll_interval=0.0)
    assert st["state"] == "inactive"


def test_wait_timeout_raises_job_wait_timeout(tmp_path):
    shell = _shell(rc=0)  # always "active"
    with patch("wb_cli.lib.job.time.sleep"), patch(
        "wb_cli.lib.job.time.time", side_effect=[0.0, 100.0, 200.0]
    ):
        with pytest.raises(WbCliError) as exc:
            JobManager(shell, jobs_dir=tmp_path).wait("u", timeout=50.0, poll_interval=0.0)
    assert exc.value.code == "JOB_WAIT_TIMEOUT"


def test_gc_removes_stale_job_files(tmp_path):
    old = tmp_path / "old-job.label"
    fresh = tmp_path / "fresh-job.label"
    old.write_text("old")
    fresh.write_text("fresh")
    # Backdate "old" by 48 hours.
    import os
    import time as _time

    past = _time.time() - 48 * 3600
    os.utime(old, (past, past))
    for suffix in (".sh", ".log", ".started"):
        (tmp_path / f"old-job{suffix}").write_text("x")
        os.utime(tmp_path / f"old-job{suffix}", (past, past))

    mgr = JobManager(_shell(), jobs_dir=tmp_path)
    mgr._gc()  # pylint: disable=protected-access
    assert not old.exists()
    assert fresh.exists()
