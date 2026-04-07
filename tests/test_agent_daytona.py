from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services.github.agent_daytona import (
    _STANDARD_TOOL_PATH,
    _posix_sh_gh_install_script,
    ensure_github_cli_installed,
)


@pytest.mark.unit
def test_gh_install_script_is_idempotent_and_uses_bounded_curl():
    script = _posix_sh_gh_install_script(bin_dir="/home/daytona/bin", version="2.88.1")

    assert 'if [ -x "$BIN/gh" ]; then' in script
    assert "--connect-timeout 20 --max-time 180" in script
    assert "install " in script
    assert '"$BIN/gh" version' not in script


@pytest.mark.unit
def test_ensure_github_cli_installed_uses_unbounded_exec_timeout_for_install():
    sandbox = object()
    probe_result = SimpleNamespace(exit_code=1, result="")
    install_result = SimpleNamespace(exit_code=0, result="ok")
    exec_mock = Mock(side_effect=[probe_result, install_result])

    with patch("services.github.agent_daytona._exec_sh", exec_mock):
        ensure_github_cli_installed(
            sandbox,
            sandbox_home="/home/daytona",
            path_for_check="/home/daytona/bin:/usr/bin",
        )

    assert exec_mock.call_count == 2
    assert exec_mock.call_args_list[0].kwargs["timeout"] == 60
    assert exec_mock.call_args_list[0].kwargs["env"] == {
        "PATH": "/home/daytona/bin:/usr/bin"
    }
    assert exec_mock.call_args_list[1].kwargs["timeout"] == 0
    assert exec_mock.call_args_list[1].kwargs["env"] == {"PATH": _STANDARD_TOOL_PATH}


@pytest.mark.unit
def test_ensure_github_cli_installed_rechecks_after_install_exception():
    sandbox = object()
    probe_missing = SimpleNamespace(exit_code=1, result="")
    probe_present = SimpleNamespace(exit_code=0, result="")
    exec_mock = Mock(side_effect=[probe_missing, RuntimeError("timeout"), probe_present])

    with patch("services.github.agent_daytona._exec_sh", exec_mock):
        ensure_github_cli_installed(
            sandbox,
            sandbox_home="/home/daytona",
            path_for_check="/home/daytona/bin:/usr/bin",
        )

    assert exec_mock.call_count == 3
    assert exec_mock.call_args_list[2].kwargs["timeout"] == 60
