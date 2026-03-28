#!/usr/bin/env bash
# uninstall.sh — Remove twingate-tray (binary, polkit policy, .desktop files)
# Usage: sudo ./scripts/uninstall.sh [--purge]
#   --purge   Also remove user config directory

set -euo pipefail

INSTALL_BIN="/usr/local/bin"
POLKIT_DIR="/usr/share/polkit-1/actions"
DESKTOP_DIR="/usr/share/applications"
PURGE=false

# Resolve the real user's home when running under sudo
if [[ -n "${SUDO_USER:-}" ]]; then
    REAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
    REAL_HOME="$HOME"
fi
AUTOSTART_DIR="$REAL_HOME/.config/autostart"
CONFIG_DIR="$REAL_HOME/.config/twingate-tray"

echo "=== twingate-tray uninstaller ==="

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --purge)
            PURGE=true
            shift
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

# Remove binary
if [[ -f "$INSTALL_BIN/twingate-tray" ]]; then
    rm "$INSTALL_BIN/twingate-tray"
    echo "Removed binary from $INSTALL_BIN"
else
    echo "Binary not found in $INSTALL_BIN (skipping)"
fi

# Remove polkit policy
if [[ -f "$POLKIT_DIR/org.twingatetray.policy" ]]; then
    rm "$POLKIT_DIR/org.twingatetray.policy"
    echo "Removed polkit policy"
else
    echo "Polkit policy not found (skipping)"
fi

# Remove .desktop file from applications
if [[ -f "$DESKTOP_DIR/twingate-tray.desktop" ]]; then
    rm "$DESKTOP_DIR/twingate-tray.desktop"
    echo "Removed .desktop file from $DESKTOP_DIR"
else
    echo ".desktop file not found in $DESKTOP_DIR (skipping)"
fi

# Remove autostart entry (user-level)
if [[ -f "$AUTOSTART_DIR/twingate-tray.desktop" ]]; then
    rm "$AUTOSTART_DIR/twingate-tray.desktop"
    echo "Removed autostart entry"
else
    echo "Autostart entry not found (skipping)"
fi

# Optionally purge user config
if [[ "$PURGE" == true ]]; then
    if [[ -d "$CONFIG_DIR" ]]; then
        rm -rf "$CONFIG_DIR"
        echo "Removed config directory: $CONFIG_DIR"
    else
        echo "Config directory not found (skipping)"
    fi
else
    echo ""
    echo "Note: User config at $CONFIG_DIR was NOT removed."
    echo "To remove it: rm -rf $CONFIG_DIR"
    echo "Or re-run with --purge: sudo ./scripts/uninstall.sh --purge"
fi

echo ""
echo "=== Uninstall complete ==="
