"""Error paths and parsing of wb_cli.lib.journal.JournalReader."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.journal import JournalReader


def _shell_returning(rc, stdout="", stderr=""):
    shell = MagicMock()
    shell.run.return_value = (rc, stdout, stderr)
    return shell


def _shell_raising(code: str):
    shell = MagicMock()
    shell.run.side_effect = WbCliError(code=code, message="x", exit_code=3)
    return shell


def test_read_parses_ndjson():
    stdout = '{"MESSAGE":"a","PRIORITY":"6"}\n{"MESSAGE":"b"}\n'
    entries = JournalReader(_shell_returning(0, stdout)).read(unit="wb-mqtt-serial")
    assert entries == [{"MESSAGE": "a", "PRIORITY": "6"}, {"MESSAGE": "b"}]


def test_read_skips_invalid_json_lines():
    entries = JournalReader(_shell_returning(0, '{"ok":1}\nGARBAGE\n')).read()
    assert entries == [{"ok": 1}]


def test_read_passes_filters_to_journalctl():
    shell = _shell_returning(0, "")
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
    assert ["-u", "wb-mqtt-serial"] == cmd[cmd.index("-u") : cmd.index("-u") + 2]
    assert ["--since", "2026-05-11 10:00:00"] == cmd[cmd.index("--since") : cmd.index("--since") + 2]
    assert ["--until", "2026-05-11 11:00:00"] == cmd[cmd.index("--until") : cmd.index("--until") + 2]
    assert ["-n", "100"] == cmd[cmd.index("-n") : cmd.index("-n") + 2]
    assert ["-p", "err"] == cmd[cmd.index("-p") : cmd.index("-p") + 2]


def test_read_translates_fs_not_found_to_journal_unavailable():
    with pytest.raises(WbCliError) as exc:
        JournalReader(_shell_raising("FS_NOT_FOUND")).read()
    assert exc.value.code == "JOURNAL_UNAVAILABLE"


def test_read_invalid_time_string_raises_journal_invalid_time():
    shell = _shell_returning(1, "", "Invalid time specification: garbage")
    with pytest.raises(WbCliError) as exc:
        JournalReader(shell).read(since="garbage")
    assert exc.value.code == "JOURNAL_INVALID_TIME"


def test_read_other_shell_error_propagates():
    with pytest.raises(WbCliError) as exc:
        JournalReader(_shell_raising("TIMEOUT")).read()
    assert exc.value.code == "TIMEOUT"
