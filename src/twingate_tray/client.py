"""TwingateClient — subprocess wrapper for the Twingate CLI."""

import enum
import logging
import re
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TWINGATE_BIN = "/usr/bin/twingate"
PKEXEC_BIN = "/usr/bin/pkexec"
DEFAULT_TIMEOUT = 15  # seconds for read-only commands
PRIVILEGED_TIMEOUT = 30  # seconds for state-changing commands

# Pattern for validating CLI arguments (account names, node IDs, resource names)
_SAFE_ARG_RE = re.compile(r"^[a-zA-Z0-9._@:/ -]+$")


class ConnectionState(enum.Enum):
    """Possible Twingate connection states."""

    ONLINE = "online"
    OFFLINE = "offline"
    CONNECTING = "connecting"
    PAUSED = "paused"
    UNKNOWN = "unknown"


@dataclass
class CommandResult:
    """Raw result from a twingate CLI invocation."""

    success: bool
    stdout: str
    stderr: str
    returncode: int


@dataclass
class TwingateStatus:
    """Parsed result from `twingate status`."""

    state: ConnectionState
    network: str | None = None
    account: str | None = None
    raw_output: str = ""


@dataclass
class TwingateResource:
    """A single Twingate resource."""

    name: str
    address: str
    is_accessible: bool = True


@dataclass
class TwingateAccount:
    """A configured Twingate account."""

    name: str
    is_active: bool = False


@dataclass
class TwingateExitNode:
    """An available exit node."""

    name: str
    is_active: bool = False


class TwingateClient:
    """Subprocess wrapper for all Twingate CLI interactions.

    Every command is run with the ``-d`` flag to disable ANSI colors,
    ensuring reliable stdout parsing.  Privileged commands are executed
    through ``pkexec`` for polkit-based privilege escalation.
    """

    @staticmethod
    def _validate_arg(value: str, label: str) -> str:
        """Validate a user-provided CLI argument to prevent option injection."""
        if not value or not _SAFE_ARG_RE.match(value):
            raise ValueError(f"Invalid {label}: {value!r}")
        if value.startswith("-"):
            raise ValueError(f"{label} must not start with '-': {value!r}")
        return value

    def _run(
        self,
        args: list[str],
        *,
        privileged: bool = False,
        timeout: int | None = None,
    ) -> CommandResult:
        """Run a twingate command and return the result."""
        cmd = [TWINGATE_BIN, *args, "-d"]
        if privileged:
            cmd = [PKEXEC_BIN, *cmd]
        if timeout is None:
            timeout = PRIVILEGED_TIMEOUT if privileged else DEFAULT_TIMEOUT
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                returncode=result.returncode,
            )
        except subprocess.TimeoutExpired:
            logger.error("Command timed out: %s", " ".join(cmd))
            return CommandResult(success=False, stdout="", stderr="timeout", returncode=-1)
        except FileNotFoundError:
            logger.error("twingate binary not found")
            return CommandResult(success=False, stdout="", stderr="not found", returncode=-1)
        except OSError as exc:
            logger.error("Failed to execute command: %s", exc)
            return CommandResult(success=False, stdout="", stderr=str(exc), returncode=-1)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def status(self, verbose: bool = False) -> TwingateStatus:
        """Get current connection status."""
        args = ["status"]
        if verbose:
            args.append("-v")
        result = self._run(args)
        return self._parse_status(result)

    def start(self) -> CommandResult:
        """Full connect — triggers browser auth if needed."""
        return self._run(["start"], privileged=True)

    def stop(self) -> CommandResult:
        """Full disconnect — clears session."""
        return self._run(["stop"], privileged=True)

    def connect(self) -> CommandResult:
        """Resume a paused connection (keeps tokens)."""
        return self._run(["connect"], privileged=True)

    def disconnect(self) -> CommandResult:
        """Pause connection without clearing tokens."""
        return self._run(["disconnect"], privileged=True)

    def desktop_start(self) -> CommandResult:
        """Start the desktop notification feed."""
        return self._run(["desktop-start"])

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    def resources(self, include_hidden: bool = False) -> list[TwingateResource]:
        """List authorized resources."""
        args = ["resources"]
        if include_hidden:
            args.append("--all")
        result = self._run(args)
        return self._parse_resources(result)

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------

    def account_list(self) -> list[TwingateAccount]:
        """List all configured accounts."""
        result = self._run(["account", "list"])
        return self._parse_accounts(result)

    def account_add(self, network: str | None = None) -> CommandResult:
        """Add a new account. Optionally pass network name."""
        args = ["account", "add"]
        if network:
            args.append(self._validate_arg(network, "network"))
        return self._run(args, privileged=True)

    def account_switch(self, account_id: str) -> CommandResult:
        """Switch to a different account."""
        self._validate_arg(account_id, "account_id")
        return self._run(["account", "switch", account_id], privileged=True)

    def account_logout(self, account_id: str | None = None) -> CommandResult:
        """Log out of current or specified account."""
        args = ["account", "logout"]
        if account_id:
            args.append(self._validate_arg(account_id, "account_id"))
        return self._run(args, privileged=True)

    # ------------------------------------------------------------------
    # Exit nodes
    # ------------------------------------------------------------------

    def exit_node_list(self) -> list[TwingateExitNode]:
        """List available exit nodes."""
        result = self._run(["exit-node", "list"])
        return self._parse_exit_nodes(result)

    def exit_node_start(self) -> CommandResult:
        """Start routing all traffic through exit node."""
        return self._run(["exit-node", "start"], privileged=True)

    def exit_node_stop(self) -> CommandResult:
        """Stop exit node routing."""
        return self._run(["exit-node", "stop"], privileged=True)

    def exit_node_switch(self, node_id: str) -> CommandResult:
        """Switch to a different exit node."""
        self._validate_arg(node_id, "node_id")
        return self._run(["exit-node", "switch", node_id], privileged=True)

    # ------------------------------------------------------------------
    # Auth & info
    # ------------------------------------------------------------------

    def auth(self, resource: str | None = None) -> CommandResult:
        """Initiate auth for a locked resource (opens browser)."""
        args = ["auth"]
        if resource:
            args.append(self._validate_arg(resource, "resource"))
        return self._run(args)

    def version(self) -> str:
        """Return the twingate CLI version string."""
        result = self._run(["version"])
        return result.stdout if result.success else "unknown"

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_status(result: CommandResult) -> TwingateStatus:
        """Parse ``twingate status [-v]`` output."""
        raw = result.stdout
        if not result.success:
            return TwingateStatus(state=ConnectionState.UNKNOWN, raw_output=raw)

        first_line = raw.splitlines()[0].strip().lower() if raw else ""

        state_map: dict[str, ConnectionState] = {
            "online": ConnectionState.ONLINE,
            "offline": ConnectionState.OFFLINE,
            "connecting": ConnectionState.CONNECTING,
            "paused": ConnectionState.PAUSED,
        }
        state = state_map.get(first_line, ConnectionState.UNKNOWN)

        # Verbose output may contain "Network: <name>" / "Account: <name>"
        network: str | None = None
        account: str | None = None
        for line in raw.splitlines():
            line_stripped = line.strip()
            if line_stripped.lower().startswith("network:"):
                network = line_stripped.split(":", 1)[1].strip() or None
            elif line_stripped.lower().startswith("account:"):
                account = line_stripped.split(":", 1)[1].strip() or None

        return TwingateStatus(
            state=state, network=network, account=account, raw_output=raw
        )

    @staticmethod
    def _parse_resources(result: CommandResult) -> list[TwingateResource]:
        """Parse ``twingate resources`` output into a list of resources.

        Expected formats (colors disabled):
          resource_name    address
          resource_name    address    status_info
        Lines that look like headers or separators are skipped.
        """
        if not result.success or not result.stdout:
            return []

        resources: list[TwingateResource] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("-") or line.lower().startswith("name"):
                continue
            # Split on 2+ whitespace characters to separate columns
            parts = re.split(r"\s{2,}", line)
            if len(parts) >= 2:
                name = parts[0].strip()
                address = parts[1].strip()
                is_accessible = True
                if len(parts) >= 3:
                    status = parts[2].strip().lower()
                    is_accessible = "denied" not in status and "locked" not in status
                resources.append(
                    TwingateResource(name=name, address=address, is_accessible=is_accessible)
                )
            elif len(parts) == 1 and parts[0]:
                # Single column — treat as name=address
                resources.append(TwingateResource(name=parts[0], address=parts[0]))

        return resources

    @staticmethod
    def _parse_accounts(result: CommandResult) -> list[TwingateAccount]:
        """Parse ``twingate account list`` output.

        Lines containing a check mark or asterisk indicate the active account.
        """
        if not result.success or not result.stdout:
            return []

        accounts: list[TwingateAccount] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("-") or line.lower().startswith("account"):
                continue
            is_active = bool(re.search(r"[✓✔*]", line))
            # Remove marker characters to get the clean name
            name = re.sub(r"[✓✔*]", "", line).strip()
            # Also remove leading/trailing whitespace and common prefixes
            name = re.sub(r"^\s*[-•]\s*", "", name).strip()
            if name:
                accounts.append(TwingateAccount(name=name, is_active=is_active))

        return accounts

    @staticmethod
    def _parse_exit_nodes(result: CommandResult) -> list[TwingateExitNode]:
        """Parse ``twingate exit-node list`` output.

        Lines containing a check mark or asterisk indicate the active node.
        """
        if not result.success or not result.stdout:
            return []

        nodes: list[TwingateExitNode] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("-") or line.lower().startswith("exit"):
                continue
            is_active = bool(re.search(r"[✓✔*]", line))
            name = re.sub(r"[✓✔*]", "", line).strip()
            name = re.sub(r"^\s*[-•]\s*", "", name).strip()
            if name:
                nodes.append(TwingateExitNode(name=name, is_active=is_active))

        return nodes
