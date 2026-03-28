# twingate-tray

A system tray application for the Twingate Linux CLI, providing a graphical interface for
connection management, resource visibility, account switching, and exit node routing.

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-alpha-orange)

---

> **Notice:** This project was developed in collaboration with an LLM-based coding assistant.
> While the code has been reviewed and tested, users should perform their own review and testing
> before using it in any environment. See the [Security](#security) section below.

---

## Overview

twingate-tray wraps the [Twingate](https://www.twingate.com/) Linux CLI with a PyQt6 system tray
icon, giving you point-and-click access to connection controls, resource lists, and account
management without opening a terminal.

This project is not affiliated with or endorsed by Twingate, Inc. It is an independent,
open-source tool built on top of the publicly available Twingate Linux CLI.

## How It Works

twingate-tray is a thin GUI layer over the Twingate CLI. It does not communicate with Twingate
servers directly and has no access to your credentials or authentication tokens.

1. **Status polling** -- A background timer runs `twingate status` at a configurable interval
   (default: every 10 seconds) and updates the tray icon to reflect the current connection state.
2. **Subprocess execution** -- Every action (connect, disconnect, list resources, etc.) is
   performed by running the `twingate` CLI binary as a subprocess. The app parses the CLI's
   text output to populate menus and display state.
3. **Privilege escalation** -- Commands that modify connection state (connect, disconnect,
   account switch, etc.) require root. These are executed through `pkexec` (polkit), which
   prompts for your password through your desktop environment's standard authentication dialog.
   Read-only commands (status, resource list) run without elevation.
4. **No persistent state** -- The app stores only user preferences (poll interval, autostart
   toggle, hidden resources toggle) in `~/.config/twingate-tray/config.json`. It never stores
   or handles passwords, tokens, or API keys. Authentication is managed entirely by the
   Twingate CLI's browser-based auth flow.

## Screenshots

Screenshots coming soon.

## Features

- Colour-coded tray icon: connected (green), disconnected (red), connecting (yellow), paused (gray)
- One-click connect, disconnect, pause, and resume
- Resource list with address copy to clipboard
- Account switching and logout
- Exit node selection and routing control
- Desktop notifications for state changes
- Configurable poll interval (1--300 seconds, default: 10)
- Optional autostart at login via `.desktop` entry
- Single-instance enforcement -- launching a second copy exits with a notification
- No credentials stored -- authentication is handled entirely by the Twingate CLI

---

## Security

**This software runs CLI commands with root privileges on your system.** Before installing or
running twingate-tray, you should understand the following:

### Review the code first

This project was developed with the assistance of an LLM-based coding tool. All code has been
reviewed and tested, but you should satisfy yourself that it behaves as expected before running
it on your machine. The entire codebase is open source and small enough to audit in an afternoon.

### What runs as root

The following Twingate CLI commands are executed through `pkexec` (polkit) with root privileges:

- `twingate start` / `stop` / `connect` / `disconnect`
- `twingate account add` / `switch` / `logout`
- `twingate exit-node start` / `stop` / `switch`

Your desktop environment will show a standard password prompt before each privileged operation
(or use a cached credential for up to 5 minutes, depending on your polkit configuration).

Read-only commands (`twingate status`, `twingate resources`, `twingate account list`,
`twingate exit-node list`) run without root and never trigger a password prompt.

### What runs without root

- Status polling (`twingate status`)
- Resource listing (`twingate resources`)
- Account and exit node listing
- The twingate-tray application itself

### Polkit policy

The install script places a polkit policy at `/usr/share/polkit-1/actions/org.twingatetray.policy`.
This policy is scoped exclusively to `/usr/bin/twingate` -- it cannot be used to escalate
privileges for any other binary. You can review the policy file at
[src/twingate_tray/resources/org.twingatetray.policy](src/twingate_tray/resources/org.twingatetray.policy).

### Input validation

All user-provided arguments passed to CLI commands (account names, exit node IDs) are validated
against a strict allowlist regex before being passed to `subprocess.run()`. Arguments that start
with `-` or contain shell metacharacters are rejected. Commands are always invoked as a list
(never through a shell), preventing shell injection.

### No credentials or secrets

twingate-tray never handles, stores, or transmits authentication tokens, passwords, or API keys.
The Twingate CLI manages all authentication through its own browser-based flow. The application's
config file contains only non-sensitive user preferences.

### Reporting security issues

If you discover a security vulnerability, please open an issue on the
[GitHub repository](https://github.com/benyanke/twingate-linux-gui/issues) or contact the
maintainer directly.

---

## Prerequisites

- **Twingate Linux CLI** installed and configured (`twingate setup` completed). See the
  [Twingate documentation](https://www.twingate.com/docs/linux) for installation instructions.
- **Linux desktop environment** with a system tray (KDE, GNOME with AppIndicator extension,
  Cinnamon, XFCE, and similar environments are supported).
- **polkit / pkexec** -- required for privilege escalation. Most desktop Linux distributions
  include this by default.
- **Python 3.12 or later** -- only required when installing from source.

---

## Installation

### Option 1: Binary download (recommended)

Download the pre-built binary from the
[GitHub Releases](https://github.com/benyanke/twingate-linux-gui/releases) page, then use the
install script to set up the polkit policy and desktop entry:

```bash
# Download the latest release (replace vX.Y.Z with the version)
curl -L https://github.com/benyanke/twingate-linux-gui/releases/download/vX.Y.Z/twingate-tray \
  -o /tmp/twingate-tray
curl -L https://github.com/benyanke/twingate-linux-gui/releases/download/vX.Y.Z/install.sh \
  -o /tmp/install.sh

# Review the install script before running it
less /tmp/install.sh

# Run the installer (copies binary, polkit policy, and .desktop file)
chmod +x /tmp/install.sh
sudo bash /tmp/install.sh
```

### Option 2: .deb package (Debian / Ubuntu)

Download the `.deb` file from the
[GitHub Releases](https://github.com/benyanke/twingate-linux-gui/releases) page:

```bash
# Replace X.Y.Z with the release version
sudo dpkg -i twingate-tray_X.Y.Z_amd64.deb
```

The package installs the binary, polkit policy, and `.desktop` file automatically.

### Option 3: From source

```bash
# 1. Clone the repository
git clone https://github.com/benyanke/twingate-linux-gui.git
cd twingate-linux-gui

# 2. Create and activate a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Install the package and its dependencies
pip install -e .

# 4. Install the polkit policy and optional autostart entry
sudo bash scripts/install.sh
```

### Uninstalling

```bash
# If installed via .deb:
sudo dpkg -r twingate-tray

# If installed via install script or from source:
sudo bash scripts/uninstall.sh

# To also remove user config:
sudo bash scripts/uninstall.sh --purge
```

---

## Usage

### Launching

```bash
# If installed via binary or .deb:
twingate-tray

# If installed from source (with .venv active):
python -m twingate_tray
```

twingate-tray starts silently and places an icon in your system tray. It does not open a window.
If a second instance is launched, it exits immediately and logs a message.

### Tray icon states

| Icon colour | Meaning              |
|-------------|----------------------|
| Green       | Connected            |
| Red         | Disconnected         |
| Yellow      | Connecting           |
| Gray        | Paused               |

### Context menu

Right-click the tray icon to access the menu:

- **Status line** -- shows current connection state and network name (not clickable)
- **Connect / Disconnect / Pause / Resume** -- control the connection state (varies by current state)
- **Resources** -- lists authorised resources with their addresses; click a resource to copy its address to the clipboard
- **Accounts** -- lists configured accounts with the active one checked; click to switch, or use Add Account / Logout
- **Exit Nodes** -- lists available exit nodes; enable, disable, or switch routing
- **Re-authenticate** -- opens the browser for Twingate re-authentication
- **Settings** -- submenu with poll interval, autostart toggle, and show hidden resources toggle
- **About** -- shows twingate-tray and CLI versions
- **Quit** -- exits the application

---

## Configuration

Configuration is stored in `~/.config/twingate-tray/config.json` and is created with sensible
defaults on first run. You do not need to create or edit this file manually -- all settings are
accessible through the tray menu under Settings.

| Setting                | Default | Description                                             |
|------------------------|---------|---------------------------------------------------------|
| `poll_interval`        | `10`    | How often (in seconds) to poll `twingate status`. Range: 1--300. |
| `autostart`            | `false` | Launch twingate-tray automatically at login.            |
| `show_hidden_resources`| `false` | Include hidden resources in the resource list.          |

Example `config.json`:

```json
{
  "poll_interval": 10,
  "autostart": false,
  "show_hidden_resources": false
}
```

### Environment variable overrides

All settings can be overridden with environment variables using the `TWINGATE_TRAY_` prefix.
Environment variables take precedence over the config file.

| Environment variable                    | Corresponding setting     |
|-----------------------------------------|---------------------------|
| `TWINGATE_TRAY_POLL_INTERVAL`           | `poll_interval`           |
| `TWINGATE_TRAY_AUTOSTART`               | `autostart`               |
| `TWINGATE_TRAY_SHOW_HIDDEN_RESOURCES`   | `show_hidden_resources`   |

---

## Building from Source

```bash
# Clone and enter the repository
git clone https://github.com/benyanke/twingate-linux-gui.git
cd twingate-linux-gui

# Create and activate a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install development dependencies
pip install -r requirements-dev.txt
pip install -e .

# Run the linter, type checker, and tests
ruff check .
mypy src/
QT_QPA_PLATFORM=offscreen pytest

# Build a standalone binary with PyInstaller
pip install pyinstaller
pyinstaller packaging/twingate-tray.spec
```

The binary is written to `dist/twingate-tray`.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and pull request
guidelines.

---

## License

MIT. See [LICENSE](LICENSE) for the full text.
