import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).resolve().parents[2] / "data" / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

RISK_PROFILES = {
    "conservative": {
        "label": "Консервативный",
        "weights": {"technical": 0.30, "fundamental": 0.25, "geo": 0.20, "ml": 0.08, "sentiment": 0.07, "mtf": 0.10},
        "max_position_pct": 10,
        "min_confidence": 0.4,
        "geo_threshold": 6.0,
        "description": "Низкий риск, приоритет фундаментального анализа и геополитики",
    },
    "balanced": {
        "label": "Умеренный",
        "weights": {"technical": 0.35, "fundamental": 0.18, "geo": 0.17, "ml": 0.13, "sentiment": 0.12, "mtf": 0.05},
        "max_position_pct": 20,
        "min_confidence": 0.3,
        "geo_threshold": 7.0,
        "description": "Сбалансированный риск, стандартные веса",
    },
    "aggressive": {
        "label": "Агрессивный",
        "weights": {"technical": 0.40, "fundamental": 0.10, "geo": 0.10, "ml": 0.20, "sentiment": 0.15, "mtf": 0.05},
        "max_position_pct": 35,
        "min_confidence": 0.2,
        "geo_threshold": 8.0,
        "description": "Высокий риск, упор на технический и ML анализ",
    },
}


@dataclass
class UserProfile:
    user_id: str
    risk_profile: str = "balanced"
    investment_horizon: str = "medium"  # short, medium, long
    capital: float = 100_000
    preferences: dict = field(
        default_factory=lambda: {
            "sectors": [],
            "exclude_tickers": [],
            "min_dividend_yield": 0.0,
            "max_position_pct": 30,
        }
    )

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "risk_profile": self.risk_profile,
            "investment_horizon": self.investment_horizon,
            "capital": self.capital,
            "preferences": self.preferences,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserProfile":
        return cls(
            user_id=data.get("user_id", "default"),
            risk_profile=data.get("risk_profile", "balanced"),
            investment_horizon=data.get("investment_horizon", "medium"),
            capital=data.get("capital", 100_000),
            preferences=data.get("preferences", {}),
        )


class UserProfileManager:
    def __init__(self):
        self._cache: dict[str, UserProfile] = {}

    def _path(self, user_id: str) -> Path:
        return PROFILES_DIR / f"{user_id}.json"

    def get(self, user_id: str) -> UserProfile:
        if user_id in self._cache:
            return self._cache[user_id]
        path = self._path(user_id)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            profile = UserProfile.from_dict(data)
        else:
            profile = UserProfile(user_id=user_id)
            self.save(profile)
        self._cache[user_id] = profile
        return profile

    def save(self, profile: UserProfile):
        path = self._path(profile.user_id)
        path.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._cache[profile.user_id] = profile

    def update(self, user_id: str, **kwargs) -> UserProfile:
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
        return min(profile.preferences.get("max_position_pct", 30), profile_data["max_position_pct"])

    def get_min_confidence(self, user_id: str) -> float:
        profile = self.get(user_id)
        profile_data = RISK_PROFILES.get(profile.risk_profile, RISK_PROFILES["balanced"])
        return profile_data["min_confidence"]

    def get_geo_threshold(self, user_id: str) -> float:
        profile = self.get(user_id)
        profile_data = RISK_PROFILES.get(profile.risk_profile, RISK_PROFILES["balanced"])
        return profile_data["geo_threshold"]

    def list_profiles(self) -> list[str]:
        return list(PROFILES_DIR.glob("*.json"))

    def delete(self, user_id: str):
        self._cache.pop(user_id, None)
        path = self._path(user_id)
        if path.exists():
            path.unlink()


profile_manager = UserProfileManager()
