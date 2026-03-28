#!/usr/bin/env bash
# install.sh — Install twingate-tray (binary, polkit policy, .desktop file)
# Usage: sudo ./scripts/install.sh [--binary PATH]
#   --binary PATH   Path to the twingate-tray binary (default: looks in dist/)

set -euo pipefail

INSTALL_BIN="/usr/local/bin"
POLKIT_DIR="/usr/share/polkit-1/actions"
DESKTOP_DIR="/usr/share/applications"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

BINARY_PATH=""

echo "=== twingate-tray installer ==="

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --binary)
            BINARY_PATH="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check for root
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

# Check for twingate CLI
if ! command -v twingate &>/dev/null; then
    echo "ERROR: twingate CLI is not installed."
    echo "Install it first: https://www.twingate.com/docs/linux"
    exit 1
fi
echo "Found twingate CLI: $(command -v twingate)"

# Detect distro
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        echo "${ID:-unknown}"
    elif command -v lsb_release &>/dev/null; then
        lsb_release -si | tr '[:upper:]' '[:lower:]'
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)
echo "Detected distro: $DISTRO"

# Find binary
if [[ -z "$BINARY_PATH" ]]; then
    if [[ -f "$PROJECT_DIR/dist/twingate-tray" ]]; then
        BINARY_PATH="$PROJECT_DIR/dist/twingate-tray"
    else
        echo "ERROR: No binary found. Build first with:"
        echo "  pyinstaller packaging/twingate-tray.spec"
        echo "Or specify: sudo ./scripts/install.sh --binary /path/to/twingate-tray"
        exit 1
    fi
fi

if [[ ! -f "$BINARY_PATH" ]]; then
    echo "ERROR: Binary not found at $BINARY_PATH"
    exit 1
fi

# Install binary
echo "Installing binary..."
install -m 755 "$BINARY_PATH" "$INSTALL_BIN/twingate-tray"
echo "  -> $INSTALL_BIN/twingate-tray"

# Install polkit policy
echo "Installing polkit policy..."
install -m 644 "$PROJECT_DIR/src/twingate_tray/resources/org.twingatetray.policy" "$POLKIT_DIR/"
echo "  -> $POLKIT_DIR/org.twingatetray.policy"

# Install .desktop file
echo "Installing .desktop file..."
install -m 644 "$PROJECT_DIR/packaging/twingate-tray.desktop" "$DESKTOP_DIR/"
echo "  -> $DESKTOP_DIR/twingate-tray.desktop"

# Optionally install autostart for the invoking user
if [[ -n "${SUDO_USER:-}" ]]; then
    REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
    AUTOSTART_DIR="$REAL_HOME/.config/autostart"
    read -rp "Enable autostart for $SUDO_USER? [y/N] " enable_autostart
    if [[ "${enable_autostart,,}" == "y" ]]; then
        mkdir -p "$AUTOSTART_DIR"
        install -m 644 "$PROJECT_DIR/packaging/twingate-tray.desktop" "$AUTOSTART_DIR/"
        echo "  -> $AUTOSTART_DIR/twingate-tray.desktop"
    fi
fi

echo ""
echo "=== Installation complete ==="
echo "Launch twingate-tray from your application menu or run: twingate-tray"
