"""Tests for config"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch


class TestLoadPersonalSettings:
    def test_invalid_yaml(self, tmp_path: Path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("{invalid: [}")

        with patch("src.config.PERSONAL_CONFIG_PATH", bad):
            from src.config import load_personal_settings

            result = load_personal_settings()
            assert result == {}

    def test_missing_file(self, tmp_path: Path):
        missing = tmp_path / "nope.yaml"

        with patch("src.config.PERSONAL_CONFIG_PATH", missing):
            from src.config import load_personal_settings

            result = load_personal_settings()
            assert result == {}

    def test_load_valid_yaml(self, tmp_path: Path):
        valid = tmp_path / "valid.yaml"
        valid.write_text("key: value")

        with patch("src.config.PERSONAL_CONFIG_PATH", valid):
            from src.config import load_personal_settings

            result = load_personal_settings()
            assert result == {"key": "value"}
