from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.user_profile import PROFILES_DIR, UserProfile, UserProfileManager, RISK_PROFILES


class TestUserProfile:
    def test_default_profile(self):
        p = UserProfile(user_id="test_user")
        assert p.user_id == "test_user"
        assert p.risk_profile == "balanced"
        assert p.investment_horizon == "medium"
        assert p.capital == 100_000

    def test_to_dict_roundtrip(self):
        p = UserProfile(user_id="u1", risk_profile="aggressive", capital=50000)
        data = p.to_dict()
        assert data["user_id"] == "u1"
        assert data["risk_profile"] == "aggressive"
        assert data["capital"] == 50000

        p2 = UserProfile.from_dict(data)
        assert p2.user_id == "u1"
        assert p2.risk_profile == "aggressive"
        assert p2.capital == 50000

    def test_from_dict_defaults(self):
        p = UserProfile.from_dict({"user_id": "u2"})
        assert p.risk_profile == "balanced"
        assert p.capital == 100_000

    def test_risk_profiles_defined(self):
        assert "conservative" in RISK_PROFILES
        assert "balanced" in RISK_PROFILES
        assert "aggressive" in RISK_PROFILES


class TestUserProfileManager:
    @pytest.fixture(autouse=True)
    def temp_profiles_dir(self, tmp_path):
        original = PROFILES_DIR
        import src.user_profile as up
        up.PROFILES_DIR = tmp_path / "profiles"
        up.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        yield
        up.PROFILES_DIR = original

    def test_get_creates_default(self):
        manager = UserProfileManager()
        p = manager.get("new_user")
        assert p.user_id == "new_user"
        assert p.risk_profile == "balanced"

    def test_save_and_load(self):
        manager = UserProfileManager()
        p = UserProfile(user_id="save_test", risk_profile="conservative", capital=20000)
        manager.save(p)

        manager2 = UserProfileManager()
        loaded = manager2.get("save_test")
        assert loaded.risk_profile == "conservative"
        assert loaded.capital == 20000

    def test_update_profile(self):
        manager = UserProfileManager()
        manager.update("update_test", risk_profile="aggressive", capital=777)
        p = manager.get("update_test")
        assert p.risk_profile == "aggressive"
        assert p.capital == 777

    def test_get_weights_conservative(self):
        manager = UserProfileManager()
        manager.update("w_test", risk_profile="conservative")
        weights = manager.get_weights("w_test")
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.001

    def test_get_weights_horizon_adjustment(self):
        manager = UserProfileManager()
        manager.update("h_test", risk_profile="balanced", investment_horizon="long")
        weights = manager.get_weights("h_test")
        base = RISK_PROFILES["balanced"]["weights"]
        assert weights["fundamental"] > base["fundamental"]
        assert weights["technical"] < base["technical"]

    def test_get_max_position(self):
        manager = UserProfileManager()
        manager.update("mp_test", risk_profile="conservative")
        limit = manager.get_max_position("mp_test")
        assert limit <= RISK_PROFILES["conservative"]["max_position_pct"]

    def test_delete_profile(self):
        manager = UserProfileManager()
        manager.update("del_test")
        assert manager.get("del_test") is not None
        manager.delete("del_test")
        assert "del_test" not in manager._cache

    def test_list_profiles_empty(self):
        manager = UserProfileManager()
        assert manager.list_profiles() == []
