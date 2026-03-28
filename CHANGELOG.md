# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-03-28

### Added

- System tray icon with dynamic state display (connected, disconnected, connecting, paused)
- Connect, disconnect, pause, and resume actions via context menu
- Resource list submenu with clipboard copy for addresses
- Account management (list, add, switch, logout)
- Exit node management (list, enable, disable, switch routing)
- Re-authentication action (opens browser)
- Configurable status polling interval (1–300 seconds)
- Autostart toggle (manages .desktop file)
- Show/hide hidden resources toggle
- Desktop notifications for connection state changes
- Single-instance guard (prevents duplicate processes)
- Polkit integration for privilege escalation
- About dialog with app and CLI version info
- PyInstaller packaging for single-file binary distribution
- .deb package support for Debian/Ubuntu
- Install and uninstall scripts with distro detection
- GitHub Actions CI workflow (lint, type check, test) and release workflow

[Unreleased]: https://github.com/benyanke/twingate-linux-gui/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/benyanke/twingate-linux-gui/releases/tag/v0.1.0
