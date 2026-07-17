import json
import logging
from pathlib import Path
from typing import Any, Optional

from src.constants import RISK_PROFILES
from src.db.connection import get_session
from src.db.models.user import UserProfileModel

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parents[2] / "data" / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)


class UserProfile:
    def __init__(
        self,
        user_id: str,
        risk_profile: str = "balanced",
        investment_horizon: str = "medium",
        capital: float = 100_000,
        preferences: Optional[dict[str, Any]] = None,
    ) -> None:
        self.user_id = user_id
        self.risk_profile = risk_profile
        self.investment_horizon = investment_horizon
        self.capital = capital
        self.preferences = preferences or {
            "sectors": [],
            "exclude_tickers": [],
            "min_dividend_yield": 0.0,
            "max_position_pct": 30,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "risk_profile": self.risk_profile,
            "investment_horizon": self.investment_horizon,
            "capital": self.capital,
            "preferences": self.preferences,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserProfile":
        return cls(
            user_id=data.get("user_id", "default"),
            risk_profile=data.get("risk_profile", "balanced"),
            investment_horizon=data.get("investment_horizon", "medium"),
            capital=data.get("capital", 100_000),
            preferences=data.get("preferences", {}),
        )

    @classmethod
    def from_orm(cls, model: UserProfileModel) -> "UserProfile":
        return cls(
            user_id=str(model.user_id),
            risk_profile=model.risk_profile or "balanced",
            investment_horizon=model.investment_horizon or "medium",
            capital=model.capital or 100_000,
            preferences=dict(model.preferences) if model.preferences else None,
        )


def _migrate_json_to_db() -> None:
    """Migrate existing JSON profile files to the database."""
    db = get_session()
    try:
        for path in PROFILES_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                user_id = data.get("user_id", path.stem)
                existing = db.query(UserProfileModel).filter(UserProfileModel.user_id == int(user_id)).first()
                if existing:
                    continue
                model = UserProfileModel(
                    user_id=int(user_id),
                    risk_profile=data.get("risk_profile", "balanced"),
                    investment_horizon=data.get("investment_horizon", "medium"),
                    capital=data.get("capital", 100_000),
                    preferences=data.get("preferences", {}),
                )
                db.add(model)
                db.commit()
                logger.info("Migrated profile for user %s to DB", user_id)
            except Exception as e:
                logger.warning("Failed to migrate profile %s: %s", path, e)
                db.rollback()
    finally:
        db.close()


class UserProfileManager:
    def __init__(self) -> None:
        self._cache: dict[str, UserProfile] = {}

    def get(self, user_id: str) -> UserProfile:
        if user_id in self._cache:
            return self._cache[user_id]
        db = get_session()
        try:
            model = db.query(UserProfileModel).filter(UserProfileModel.user_id == int(user_id)).first()
            if model is not None:
                profile = UserProfile.from_orm(model)
            else:
                profile = UserProfile(user_id=user_id)
                self._save_to_db(db, profile)
            self._cache[user_id] = profile
            return profile
        finally:
            db.close()

    def save(self, profile: UserProfile) -> None:
        db = get_session()
        try:
            self._save_to_db(db, profile)
            self._cache[profile.user_id] = profile
        finally:
            db.close()

    def _save_to_db(self, db: Any, profile: UserProfile) -> None:
        model = db.query(UserProfileModel).filter(UserProfileModel.user_id == int(profile.user_id)).first()
        if model is None:
            model = UserProfileModel(
                user_id=int(profile.user_id),
                risk_profile=profile.risk_profile,
                investment_horizon=profile.investment_horizon,
                capital=profile.capital,
                preferences=profile.preferences,
            )
            db.add(model)
        else:
            model.risk_profile = profile.risk_profile
            model.investment_horizon = profile.investment_horizon
            model.capital = profile.capital
            model.preferences = profile.preferences
        db.commit()

    def update(self, user_id: str, **kwargs: Any) -> UserProfile:
        profile = self.get(user_id)
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
            elif key in profile.preferences:
                profile.preferences[key] = value
        self.save(profile)
        return profile

    def get_weights(self, user_id: str) -> dict[str, float]:
        profile = self.get(user_id)
        profile_data = RISK_PROFILES.get(profile.risk_profile, RISK_PROFILES["balanced"])
        weights = dict(profile_data["weights"])
        if profile.investment_horizon == "long":
            weights["fundamental"] *= 1.3
            weights["technical"] *= 0.8
        elif profile.investment_horizon == "short":
            weights["technical"] *= 1.3
            weights["fundamental"] *= 0.7
        total = sum(weights.values())
        if total > 0:
            for k in weights:
                weights[k] /= total
        return weights

    def get_max_position(self, user_id: str) -> int:
        profile = self.get(user_id)
        profile_data = RISK_PROFILES.get(profile.risk_profile, RISK_PROFILES["balanced"])
        return int(min(profile.preferences.get("max_position_pct", 30), profile_data["max_position_pct"]))

    def get_min_confidence(self, user_id: str) -> float:
        profile = self.get(user_id)
        profile_data = RISK_PROFILES.get(profile.risk_profile, RISK_PROFILES["balanced"])
        return float(profile_data["min_confidence"])

    def get_geo_threshold(self, user_id: str) -> float:
        profile = self.get(user_id)
        profile_data = RISK_PROFILES.get(profile.risk_profile, RISK_PROFILES["balanced"])
        return float(profile_data["geo_threshold"])

    def list_profiles(self) -> list[str]:
        db = get_session()
        try:
            rows = db.query(UserProfileModel.user_id).all()
            return [str(r[0]) for r in rows]
        finally:
            db.close()

    def delete(self, user_id: str) -> None:
        self._cache.pop(user_id, None)
        db = get_session()
        try:
            db.query(UserProfileModel).filter(UserProfileModel.user_id == int(user_id)).delete()
            db.commit()
        finally:
            db.close()


profile_manager = UserProfileManager()

_migrate_json_to_db()
