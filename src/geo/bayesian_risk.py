from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models.risk import GeoRiskScore

logger = logging.getLogger(__name__)


@dataclass
class CountryState:
    alpha: float
    beta: float
    updated_at: datetime | None = None


class BayesianGeoRisk:
    PRIOR_ALPHA = 2.0
    PRIOR_BETA = 20.0

    def __init__(self, db_session: Session | None = None) -> None:
        self._db = db_session
        self._countries: dict[str, CountryState] = {}

    # ── Posterior update ─────────────────────────────────────────────────────

    def update(self, country: str, signal: dict[str, Any]) -> dict[str, Any]:
        state = self._countries.setdefault(
            country,
            CountryState(alpha=self.PRIOR_ALPHA, beta=self.PRIOR_BETA),
        )

        likelihood = signal.get("likelihood", 0.5)
        likelihood = max(0.01, min(0.99, likelihood))

        observations = signal.get("observations", 1)
        for _ in range(observations):
            state.alpha += likelihood
            state.beta += 1.0 - likelihood

        state.updated_at = datetime.now(timezone.utc)

        return {
            "country": country,
            "prior_alpha": self.PRIOR_ALPHA,
            "prior_beta": self.PRIOR_BETA,
            "posterior_alpha": state.alpha,
            "posterior_beta": state.beta,
            "posterior_mean": state.alpha / (state.alpha + state.beta),
            "signal_type": signal.get("type", "unknown"),
            "signal_likelihood": likelihood,
        }

    # ── Risk queries ─────────────────────────────────────────────────────────

    def get_risk(self, country: str) -> float:
        state = self._countries.get(country)
        if state is None:
            return self.PRIOR_ALPHA / (self.PRIOR_ALPHA + self.PRIOR_BETA)
        return state.alpha / (state.alpha + state.beta)

    def get_risk_level(self, country: str) -> str:
        risk = self.get_risk(country)
        if risk > 0.8:
            return "CRITICAL"
        if risk >= 0.6:
            return "HIGH"
        if risk >= 0.3:
            return "MODERATE"
        return "LOW"

    # ── Signal fusion ────────────────────────────────────────────────────────

    def combine_signals(self, country: str, signals: list[dict[str, Any]]) -> float:
        if not signals:
            return self.get_risk(country)

        alpha = self.PRIOR_ALPHA
        beta = self.PRIOR_BETA

        for signal in signals:
            likelihood = signal.get("likelihood", 0.5)
            likelihood = max(0.01, min(0.99, likelihood))
            weight = signal.get("weight", 1.0)
            effective_obs = max(1, signal.get("observations", 1)) * weight
            alpha += likelihood * effective_obs
            beta += (1.0 - likelihood) * effective_obs

        fused_mean = alpha / (alpha + beta)

        state = self._countries.setdefault(
            country,
            CountryState(alpha=self.PRIOR_ALPHA, beta=self.PRIOR_BETA),
        )
        state.alpha = alpha
        state.beta = beta
        state.updated_at = datetime.now(timezone.utc)

        return fused_mean

    # ── DB persistence ───────────────────────────────────────────────────────

    def load_from_db(self) -> None:
        if self._db is None:
            logger.warning("No DB session — skipping load_from_db")
            return
        rows = self._db.execute(select(GeoRiskScore)).scalars().all()
        for row in rows:
            country = _derive_country_from_row(row)
            if country:
                self._countries[country] = CountryState(
                    alpha=row.score * 10.0 + 2.0,
                    beta=(1.0 - row.score) * 10.0 + 2.0,
                    updated_at=row.created_at,
                )

    def save_to_db(self) -> None:
        if self._db is None:
            logger.warning("No DB session — skipping save_to_db")
            return
        today = date.today()
        for country, state in self._countries.items():
            risk = state.alpha / (state.alpha + state.beta)
            existing = self._db.execute(select(GeoRiskScore).where(GeoRiskScore.date == today)).scalar_one_or_none()
            if existing:
                existing.score = risk
            else:
                row = GeoRiskScore(
                    date=today,
                    score=risk,
                    components_json={"country": country, "alpha": state.alpha, "beta": state.beta},
                )
                self._db.add(row)
        self._db.commit()


def _derive_country_from_row(row: GeoRiskScore) -> str | None:
    if row.components_json and isinstance(row.components_json, dict):
        return row.components_json.get("country")
    return None
