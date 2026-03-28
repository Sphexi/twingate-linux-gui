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

# Regex to strip ANSI escape codes from CLI output
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Pattern for validating CLI arguments (account names, node IDs, resource names).
# Rejects shell metacharacters (;|`$&<>!) while allowing Unicode (including emoji)
# since Twingate uses emoji prefixes in exit node names.
_SAFE_ARG_RE = re.compile(r"^[^;|`$&<>!\t\n\r]+$")


def _clean_cli_name(line: str) -> str:
    """Clean a name from CLI output by removing markers and emoji prefixes.

    Handles output like: '👤 Seattle Exit Network - Vultr\\t--'
    Returns: 'Seattle Exit Network - Vultr'
    """
    # Strip tab-separated trailing content (e.g. status columns)
    name = line.split("\t")[0].strip()
    # Remove active markers (checkmark, asterisk)
    name = re.sub(r"[✓✔*]", "", name).strip()
    # Remove leading bullet/dash markers
    name = re.sub(r"^\s*[-•]\s*", "", name).strip()
    # Remove leading emoji characters (non-ASCII, non-letter prefix)
    name = re.sub(r"^[^\w\s]+\s*", "", name, flags=re.UNICODE).strip()
    # Remove trailing decorators like '--' or '---'
    name = re.sub(r"\s*-{2,}\s*$", "", name).strip()
    return name


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
    email: str = ""
    network: str = ""

    @property
    def switch_id(self) -> str:
        """Return the identifier for ``account switch`` (email:network)."""
        if self.email and self.network:
            return f"{self.email}:{self.network}"
        return self.name


@dataclass
class TwingateExitNode:
    """An available exit node."""

    name: str
    is_active: bool = False
    cli_name: str = ""

    def __post_init__(self) -> None:
        """Default cli_name to name if not set."""
        if not self.cli_name:
            self.cli_name = self.name


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
                stdout=_ANSI_RE.sub("", result.stdout).strip(),
                stderr=_ANSI_RE.sub("", result.stderr).strip(),
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
            "not-running": ConnectionState.OFFLINE,
            "connecting": ConnectionState.CONNECTING,
            "authenticating": ConnectionState.CONNECTING,
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

        Expected format (colors disabled)::

            EMAIL              NETWORK  NETWORK URL
            user@example.com   acme     acme.twingate.com

        Also handles legacy single-column format with check/asterisk markers.
        """
        if not result.success or not result.stdout:
            return []

        accounts: list[TwingateAccount] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("-"):
                continue
            # Skip header lines
            if line.lower().startswith("email") or line.lower().startswith("account"):
                continue
            is_active = bool(re.search(r"[✓✔*]", line))
            # Split on 2+ whitespace to separate columns
            parts = re.split(r"\s{2,}", line)
            if len(parts) >= 2:
                # Columnar format: EMAIL  NETWORK  [NETWORK URL]
                email = _clean_cli_name(parts[0])
                network = parts[1].strip()
                # Display as "network (email)" for the menu label
                display_name = f"{network} ({email})" if email else network
                accounts.append(TwingateAccount(
                    name=display_name,
                    is_active=is_active,
                    email=email,
                    network=network,
                ))
            else:
                # Single-column fallback
                name = _clean_cli_name(line)
                if name:
                    accounts.append(TwingateAccount(name=name, is_active=is_active))

        return accounts

    @staticmethod
    def _parse_exit_nodes(result: CommandResult) -> list[TwingateExitNode]:
        """Parse ``twingate exit-node list`` output.

        Expected format (colors disabled)::

            Non-Resource traffic currently isn't being routed through Twingate

            EXIT NETWORK NAME                 TIME LEFT
            👤 Seattle Exit Network           --

        Lines containing a check mark, asterisk, or emoji indicate the active node.
        """
        if not result.success or not result.stdout:
            return []

        nodes: list[TwingateExitNode] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            # Skip empty, separator, header, and status description lines
            if not line or line.startswith("-") or line.lower().startswith("exit"):
                continue
            if line.lower().startswith("non-") or line.lower().startswith("all "):
                continue
            # Split on tabs or 2+ spaces to separate columns (name vs time-left)
            parts = re.split(r"\t|\s{2,}", line)
            raw_name = parts[0].strip() if parts else line.strip()
            is_active = bool(re.search(r"[✓✔*]", raw_name))
            # Clean name for display, but preserve raw name for CLI commands.
            # The CLI expects the full name including emoji prefix.
            display_name = _clean_cli_name(raw_name)
            # For cli_name: strip only active markers, keep emoji
            cli_name = re.sub(r"[✓✔*]", "", raw_name).strip()
            cli_name = re.sub(r"^\s*[-•]\s*", "", cli_name).strip()
            if display_name:
                nodes.append(TwingateExitNode(
                    name=display_name, is_active=is_active, cli_name=cli_name,
                ))

        return nodes
