"""Error paths and request shaping of wb_cli.lib.rpc.RpcClient."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from wb_cli.errors import WbCliError
from wb_cli.lib.rpc import RpcClient


def _shell_returning(rc, stdout="", stderr=""):
    shell = MagicMock()
    shell.run.return_value = (rc, stdout, stderr)
    return shell


def _shell_raising(code: str):
    shell = MagicMock()
    shell.run.side_effect = WbCliError(code=code, message="x", exit_code=3)
    return shell


def test_call_emits_dsma_flags_and_parses_json():
    shell = _shell_returning(0, '{"v": 1}')
    result = RpcClient(shell).call("drv/svc/Method", {"k": "v"})
    cmd = shell.run.call_args.args[0]
    assert cmd[0] == "mqtt-rpc-client"
    # -d drv -s svc -m Method -t <int> -a <json>
    assert cmd[1:7] == ["-d", "drv", "-s", "svc", "-m", "Method"]
    assert "-a" in cmd
    assert '"k": "v"' in cmd[cmd.index("-a") + 1]
    assert result == {"v": 1}


def test_call_without_params_omits_args_flag():
    shell = _shell_returning(0, "null")
    RpcClient(shell).call("drv/svc/Method")
    cmd = shell.run.call_args.args[0]
    assert "-a" not in cmd


def test_invalid_target_two_parts():
    with pytest.raises(WbCliError) as exc:
        RpcClient(_shell_returning(0)).call("drv/svc")
    assert exc.value.code == "RPC_INVALID_TARGET"


def test_invalid_target_empty_segment():
    with pytest.raises(WbCliError) as exc:
        RpcClient(_shell_returning(0)).call("drv//Method")
    assert exc.value.code == "RPC_INVALID_TARGET"


def test_timeout_becomes_rpc_no_reply():
    with pytest.raises(WbCliError) as exc:
        RpcClient(_shell_raising("TIMEOUT")).call("drv/svc/M")
    assert exc.value.code == "RPC_NO_REPLY"


def test_nonzero_rc_becomes_rpc_error_response():
    shell = _shell_returning(1, "", "rpc-side error")
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell).call("drv/svc/M")
    assert exc.value.code == "RPC_ERROR_RESPONSE"
    assert "rpc-side error" in exc.value.message


def test_non_json_stdout_becomes_rpc_error_response():
    shell = _shell_returning(0, "not-json-output")
    with pytest.raises(WbCliError) as exc:
        RpcClient(shell).call("drv/svc/M")
    assert exc.value.code == "RPC_ERROR_RESPONSE"
    assert "not valid JSON" in exc.value.message


def test_invalid_params_become_rpc_invalid_params():
    # Sets/tuples/etc aren't JSON-serialisable; json.dumps raises TypeError.
    class _NotJsonable:
        pass

    with pytest.raises(WbCliError) as exc:
        RpcClient(_shell_returning(0)).call("drv/svc/M", {"k": _NotJsonable()})
    assert exc.value.code == "RPC_INVALID_PARAMS"


def test_other_shell_error_propagates_untouched():
    with pytest.raises(WbCliError) as exc:
        RpcClient(_shell_raising("FS_NOT_FOUND")).call("drv/svc/M")
    assert exc.value.code == "FS_NOT_FOUND"
