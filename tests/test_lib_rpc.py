"""Error paths and request shaping of wb_cli.lib.rpc.RpcClient."""

from __future__ import annotations

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.rpc import RpcClient


def test_call_emits_dsma_flags_and_parses_json(shell_returning):
    shell = shell_returning(0, '{"v": 1}')
    result = RpcClient(shell).call("drv/svc/Method", {"k": "v"})
    cmd = shell.run.call_args.args[0]
    assert cmd[0] == "mqtt-rpc-client"
    assert cmd[1:7] == ["-d", "drv", "-s", "svc", "-m", "Method"]
    assert "-a" in cmd
    assert '"k": "v"' in cmd[cmd.index("-a") + 1]
    assert result == {"v": 1}


def test_call_without_params_omits_args_flag(shell_returning):
    shell = shell_returning(0, "null")
    RpcClient(shell).call("drv/svc/Method")
    cmd = shell.run.call_args.args[0]
    assert "-a" not in cmd


def test_invalid_target_two_parts(shell_returning):
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell_returning(0)).call("drv/svc")
    assert exc.value.code == "RPC_INVALID_TARGET"


def test_invalid_target_empty_segment(shell_returning):
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell_returning(0)).call("drv//Method")
    assert exc.value.code == "RPC_INVALID_TARGET"


def test_timeout_becomes_rpc_no_reply(shell_raising):
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell_raising("SHELL_TIMEOUT")).call("drv/svc/M")
    assert exc.value.code == "RPC_NO_REPLY"


def test_nonzero_rc_becomes_rpc_error_response(shell_returning):
    shell = shell_returning(1, "", "rpc-side error")
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell).call("drv/svc/M")
    assert exc.value.code == "RPC_ERROR_RESPONSE"
    assert "rpc-side error" in exc.value.message


def test_non_json_stdout_becomes_rpc_error_response(shell_returning):
    shell = shell_returning(0, "not-json-output")
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell).call("drv/svc/M")
    assert exc.value.code == "RPC_ERROR_RESPONSE"
    assert "not valid JSON" in exc.value.message


def test_invalid_params_become_rpc_invalid_params(shell_returning):
    # A set is not JSON-serialisable; json.dumps raises TypeError.
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell_returning(0)).call("drv/svc/M", {"k": {1, 2, 3}})
    assert exc.value.code == "RPC_INVALID_PARAMS"


def test_other_shell_error_propagates_untouched(shell_raising):
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell_raising("FS_NOT_FOUND")).call("drv/svc/M")
    assert exc.value.code == "FS_NOT_FOUND"


def test_import_error_from_daemon_carries_upgrade_hint(shell_returning):
    """A stale daemon (e.g. wb-device-manager 1.14 on py3.9) surfaces ImportError
    on every RPC. We attach an `apt-get install -y <pkg>` hint mapped from the
    driver name so the user knows what to upgrade."""
    payload = (
        "Error: Server error [-32000]: "
        "{'type': 'ImportError', "
        "'message': \"cannot import name 'HeaderWriteError' from 'email.errors'\"}"
    )
    shell = shell_returning(1, payload, "")
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell).call("wb-device-manager/fw-update/GetFirmwareInfo")
    assert exc.value.code == "RPC_ERROR_RESPONSE"
    assert exc.value.hint is not None
    assert "wb-device-manager" in exc.value.hint
    assert "apt-get" in exc.value.hint


def test_non_import_error_carries_no_hint(shell_returning):
    """Ordinary RPC errors (timeouts, bad params) shouldn't suggest an upgrade."""
    shell = shell_returning(1, "", "Error: Server error [-32601]: method not found")
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell).call("wb-device-manager/svc/Method")
    assert exc.value.hint is None
