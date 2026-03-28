"""Entry point for twingate-tray: python -m twingate_tray."""

import sys

from twingate_tray.app import run


def main() -> None:
    """Launch the twingate-tray application."""
    sys.exit(run())


if __name__ == "__main__":
    main()
