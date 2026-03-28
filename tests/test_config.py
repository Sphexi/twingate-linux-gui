"""Unit tests for TrayConfig and ConfigManager."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from twingate_tray.config import ConfigManager, TrayConfig


class TestTrayConfig:
    """Tests for the TrayConfig Pydantic model."""

    def test_defaults(self) -> None:
        config = TrayConfig()
        assert config.poll_interval == 10
        assert config.autostart is False
        assert config.show_hidden_resources is False

    def test_custom_values(self) -> None:
        config = TrayConfig(poll_interval=30, autostart=True, show_hidden_resources=True)
        assert config.poll_interval == 30
        assert config.autostart is True
        assert config.show_hidden_resources is True

    def test_poll_interval_minimum(self) -> None:
        with pytest.raises(ValueError):
            TrayConfig(poll_interval=0)

    def test_poll_interval_maximum(self) -> None:
        with pytest.raises(ValueError):
            TrayConfig(poll_interval=999)

    def test_json_round_trip(self) -> None:
        config = TrayConfig(poll_interval=20, autostart=True)
        data = json.loads(config.model_dump_json())
        restored = TrayConfig(**data)
        assert restored == config

    # --- boundary value tests ---

    def test_poll_interval_at_lower_boundary_is_valid(self) -> None:
        """poll_interval=1 is the lowest accepted value (ge=1)."""
        config = TrayConfig(poll_interval=1)
        assert config.poll_interval == 1

    def test_poll_interval_at_upper_boundary_is_valid(self) -> None:
        """poll_interval=300 is the highest accepted value (le=300)."""
        config = TrayConfig(poll_interval=300)
        assert config.poll_interval == 300

    def test_poll_interval_just_above_upper_boundary_is_invalid(self) -> None:
        """poll_interval=301 exceeds the maximum and must be rejected."""
        with pytest.raises(ValueError):
            TrayConfig(poll_interval=301)

    # --- model_dump() structure ---

    def test_model_dump_returns_expected_keys(self) -> None:
        """model_dump() must expose exactly the three config fields."""
        config = TrayConfig()
        data = config.model_dump()
        assert set(data.keys()) == {"poll_interval", "autostart", "show_hidden_resources"}

    def test_model_dump_values_match_fields(self) -> None:
        """model_dump() values must reflect the instance field values."""
        config = TrayConfig(poll_interval=45, autostart=True, show_hidden_resources=True)
        data = config.model_dump()
        assert data["poll_interval"] == 45
        assert data["autostart"] is True
        assert data["show_hidden_resources"] is True

    # --- env var overrides ---

    def test_env_var_overrides_poll_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TWINGATE_TRAY_POLL_INTERVAL env var must override the default."""
        monkeypatch.setenv("TWINGATE_TRAY_POLL_INTERVAL", "25")
        config = TrayConfig()
        assert config.poll_interval == 25

    def test_env_var_overrides_autostart(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TWINGATE_TRAY_AUTOSTART=true must enable autostart."""
        monkeypatch.setenv("TWINGATE_TRAY_AUTOSTART", "true")
        config = TrayConfig()
        assert config.autostart is True

    def test_env_var_overrides_show_hidden_resources(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TWINGATE_TRAY_SHOW_HIDDEN_RESOURCES=true must enable the flag."""
        monkeypatch.setenv("TWINGATE_TRAY_SHOW_HIDDEN_RESOURCES", "true")
        config = TrayConfig()
        assert config.show_hidden_resources is True


class TestConfigManager:
    """Tests for ConfigManager read/write/update."""

    def test_creates_default_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        mgr = ConfigManager(config_path=config_file)
        assert mgr.config.poll_interval == 10
        assert not config_file.exists()  # Not written until save()

    def test_save_and_load(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        mgr = ConfigManager(config_path=config_file)
        mgr.save()
        assert config_file.exists()

        mgr2 = ConfigManager(config_path=config_file)
        assert mgr2.config == mgr.config

    def test_update_persists(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        mgr = ConfigManager(config_path=config_file)
        mgr.update(poll_interval=25, autostart=True)

        mgr2 = ConfigManager(config_path=config_file)
        assert mgr2.config.poll_interval == 25
        assert mgr2.config.autostart is True

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("not valid json!!!", encoding="utf-8")

        mgr = ConfigManager(config_path=config_file)
        assert mgr.config.poll_interval == 10

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        config_file = tmp_path / "deep" / "nested" / "config.json"
        mgr = ConfigManager(config_path=config_file)
        mgr.save()
        assert config_file.exists()

    def test_invalid_values_in_file_falls_back(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text('{"poll_interval": -5}', encoding="utf-8")

        mgr = ConfigManager(config_path=config_file)
        assert mgr.config.poll_interval == 10  # Defaults on validation error

    # --- update edge cases ---

    def test_update_with_invalid_poll_interval_raises_validation_error(
        self, tmp_path: Path
    ) -> None:
        """update() must raise ValidationError when the new value violates constraints."""
        config_file = tmp_path / "config.json"
        mgr = ConfigManager(config_path=config_file)
        with pytest.raises(ValidationError):
            mgr.update(poll_interval=0)

    def test_update_partial_only_changes_named_field(self, tmp_path: Path) -> None:
        """Updating one field must leave all other fields at their previous values."""
        config_file = tmp_path / "config.json"
        mgr = ConfigManager(config_path=config_file)
        mgr.update(poll_interval=60)

        assert mgr.config.poll_interval == 60
        assert mgr.config.autostart is False
        assert mgr.config.show_hidden_resources is False

    def test_consecutive_updates_persist_latest_values(self, tmp_path: Path) -> None:
        """Each successive update must overwrite the previous value on disk."""
        config_file = tmp_path / "config.json"
        mgr = ConfigManager(config_path=config_file)

        mgr.update(poll_interval=30)
        mgr.update(poll_interval=90)

        reloaded = ConfigManager(config_path=config_file)
        assert reloaded.config.poll_interval == 90

    # --- save file structure ---

    def test_save_writes_valid_json_with_correct_keys(self, tmp_path: Path) -> None:
        """The saved file must be valid JSON containing exactly the three config keys."""
        config_file = tmp_path / "config.json"
        mgr = ConfigManager(config_path=config_file)
        mgr.update(poll_interval=15, autostart=True, show_hidden_resources=True)

        raw = json.loads(config_file.read_text(encoding="utf-8"))
        assert set(raw.keys()) == {"poll_interval", "autostart", "show_hidden_resources"}
        assert raw["poll_interval"] == 15
        assert raw["autostart"] is True
        assert raw["show_hidden_resources"] is True

    # --- load edge cases ---

    def test_empty_json_object_loads_as_defaults(self, tmp_path: Path) -> None:
        """An existing file containing only `{}` must yield fully-defaulted config."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{}", encoding="utf-8")

        mgr = ConfigManager(config_path=config_file)
        assert mgr.config.poll_interval == 10
        assert mgr.config.autostart is False
        assert mgr.config.show_hidden_resources is False

    def test_json_with_extra_unknown_keys_loads_known_fields(self, tmp_path: Path) -> None:
        """TrayConfig ignores extra fields, so unknown keys in the file are
        silently discarded and known fields are loaded normally."""
        config_file = tmp_path / "config.json"
        config_file.write_text(
            '{"poll_interval": 20, "unknown_future_key": "ignored"}',
            encoding="utf-8",
        )

        mgr = ConfigManager(config_path=config_file)
        assert mgr.config.poll_interval == 20  # Known field loaded despite extra key

    def test_wrong_type_for_poll_interval_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """A non-numeric poll_interval value must trigger fallback to defaults."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"poll_interval": "abc"}', encoding="utf-8")

        mgr = ConfigManager(config_path=config_file)
        assert mgr.config.poll_interval == 10
