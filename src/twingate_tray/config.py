"""Pydantic config model and ConfigManager for twingate-tray."""

import json
import logging
import os
import sys
from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "twingate-tray"
CONFIG_FILE = CONFIG_DIR / "config.json"


class TrayConfig(BaseSettings):
    """User-configurable settings for twingate-tray."""

    model_config = SettingsConfigDict(
        env_prefix="TWINGATE_TRAY_",
        env_file=None,
        extra="ignore",
    )

    poll_interval: int = Field(
        default=10, ge=1, le=300, description="Status poll interval in seconds"
    )
    autostart: bool = Field(default=False, description="Launch at login via .desktop autostart")
    show_hidden_resources: bool = Field(
        default=False, description="Show hidden resources in the resource list"
    )


class ConfigManager:
    """Reads and writes TrayConfig to ~/.config/twingate-tray/config.json."""

    def __init__(self, config_path: Path = CONFIG_FILE) -> None:
        self._path = config_path
        self._config = self._load()

    @property
    def config(self) -> TrayConfig:
        """Return the current configuration."""
        return self._config

    def _load(self) -> TrayConfig:
        """Load config from disk, creating defaults if missing or corrupt."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return TrayConfig(**data)
        except FileNotFoundError:
            pass  # No config file yet — use defaults
        except (json.JSONDecodeError, ValidationError, OSError):
            logger.warning("Corrupt config file at %s — using defaults", self._path)
        return TrayConfig()

    def save(self) -> None:
        """Write current config to disk with restrictive permissions."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            self._path.parent.chmod(0o700)
        content = self._config.model_dump_json(indent=2) + "\n"
        if sys.platform == "win32":
            self._path.write_text(content, encoding="utf-8")
        else:
            fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)

    def update(self, **kwargs: object) -> None:
        """Update config fields and persist to disk."""
        data = self._config.model_dump()
        data.update(kwargs)
        self._config = TrayConfig(**data)
        self.save()
