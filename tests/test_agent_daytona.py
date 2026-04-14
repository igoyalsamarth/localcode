from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services.github.agent_daytona import (
    _STANDARD_TOOL_PATH,
    _posix_sh_gh_install_script,
    ensure_github_cli_installed,
)


@pytest.mark.unit
def test_gh_install_script_downloads_official_tarball_posix_sh():
    script = _posix_sh_gh_install_script(bin_dir="/home/daytona/bin", version="2.88.1")

    assert "set -eu" in script
    assert 'BIN="/home/daytona/bin"' in script or 'BIN=/home/daytona/bin' in script
    assert "curl -fsSL" in script
    assert (
        "https://github.com/cli/cli/releases/download/v2.88.1/gh_2.88.1_linux_$arch.tar.gz"
        in script
    )
    assert "tar -xzf /tmp/gh.tgz -C /tmp" in script
    assert 'cp "/tmp/gh_2.88.1_linux_$arch/bin/gh" "$BIN/gh"' in script
    assert '"$BIN/gh" version' in script


@pytest.mark.unit
def test_ensure_github_cli_installed_uses_bounded_exec_timeout_for_install():
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
    assert exec_mock.call_args_list[1].kwargs["timeout"] == 180
    assert exec_mock.call_args_list[1].kwargs["env"] == {"PATH": _STANDARD_TOOL_PATH}


@pytest.mark.unit
def test_ensure_github_cli_installed_swallows_install_exception_after_probe():
    sandbox = object()
    probe_missing = SimpleNamespace(exit_code=1, result="")
    exec_mock = Mock(side_effect=[probe_missing, RuntimeError("timeout")])

    with patch("services.github.agent_daytona._exec_sh", exec_mock):
        ensure_github_cli_installed(
            sandbox,
            sandbox_home="/home/daytona",
            path_for_check="/home/daytona/bin:/usr/bin",
        )

    assert exec_mock.call_count == 2
    assert exec_mock.call_args_list[0].kwargs["timeout"] == 60
    assert exec_mock.call_args_list[1].kwargs["timeout"] == 180
