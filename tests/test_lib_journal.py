"""Error paths and parsing of wb_cli.lib.journal.JournalReader."""

from __future__ import annotations

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.journal import JournalReader


def test_read_parses_ndjson(shell_returning):
    stdout = '{"MESSAGE":"a","PRIORITY":"6"}\n{"MESSAGE":"b"}\n'
    entries = JournalReader(shell_returning(0, stdout)).read(unit="wb-mqtt-serial")
    assert entries == [{"MESSAGE": "a", "PRIORITY": "6"}, {"MESSAGE": "b"}]


def test_read_skips_invalid_json_lines(shell_returning):
    entries = JournalReader(shell_returning(0, '{"ok":1}\nGARBAGE\n')).read()
    assert entries == [{"ok": 1}]


def test_read_passes_filters_to_journalctl(shell_returning):
    shell = shell_returning(0, "")
    JournalReader(shell).read(
        unit="wb-mqtt-serial",
        since="2026-05-11 10:00:00",
        until="2026-05-11 11:00:00",
        lines=100,
        priority="err",
    )
    cmd = shell.run.call_args.args[0]
    assert cmd[0] == "journalctl"
    assert "--output=json" in cmd
    assert cmd[cmd.index("-u") : cmd.index("-u") + 2] == ["-u", "wb-mqtt-serial"]
    assert cmd[cmd.index("--since") : cmd.index("--since") + 2] == ["--since", "2026-05-11 10:00:00"]
    assert cmd[cmd.index("--until") : cmd.index("--until") + 2] == ["--until", "2026-05-11 11:00:00"]
    assert cmd[cmd.index("-n") : cmd.index("-n") + 2] == ["-n", "100"]
    assert cmd[cmd.index("-p") : cmd.index("-p") + 2] == ["-p", "err"]


def test_read_translates_fs_not_found_to_journal_unavailable(shell_raising):
    with pytest.raises(WbCliError) as exc:
        JournalReader(shell_raising("FS_NOT_FOUND")).read()
    assert exc.value.code == "JOURNAL_UNAVAILABLE"


def test_read_invalid_time_string_raises_journal_invalid_time(shell_returning):
    shell = shell_returning(1, "", "Invalid time specification: garbage")
    with pytest.raises(WbCliError) as exc:
        JournalReader(shell).read(since="garbage")
    assert exc.value.code == "JOURNAL_INVALID_TIME"


def test_read_other_shell_error_propagates(shell_raising):
    with pytest.raises(WbCliError) as exc:
        JournalReader(shell_raising("TIMEOUT")).read()
    assert exc.value.code == "TIMEOUT"
