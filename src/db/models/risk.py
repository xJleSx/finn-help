from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)

from .base import Base


class AMLState(Base):
    __tablename__ = "aml_state"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, unique=True, index=True)
    date = Column(Date, nullable=False)
    daily_volume = Column(Float, default=0.0)
    tx_timestamps_json = Column(JSON, default=list)
    velocity_timestamps_json = Column(JSON, default=list)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class GeoRiskScore(Base):
    __tablename__ = "geo_risk_scores"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    country = Column(String(100), default="global")
    score = Column(Float, nullable=False)
    components_json = Column(JSON)
    sources_json = Column(JSON)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("date", "country", name="uq_geo_risk_date_country"),)


# Phase 3: Sector Risk History
class SectorRiskHistory(Base):
    __tablename__ = "sector_risk_history"

    id = Column(Integer, primary_key=True)
    sector = Column(String(100), nullable=False)
    date = Column(Date, nullable=False)
    risk_score = Column(Float, nullable=False)
    components_json = Column(JSON)
    article_count = Column(Integer)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("sector", "date", name="uq_sector_risk_date"),)


# Phase 4: Company Risk History
class CompanyRiskHistory(Base):
    __tablename__ = "company_risk_history"

    id = Column(Integer, primary_key=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    date = Column(Date, nullable=False)
    risk_score = Column(Float, nullable=False)
    sector_risk = Column(Float)
    geopolitical_risk = Column(Float)
    macro_risk = Column(Float)
    company_specific_risk = Column(Float)
    components_json = Column(JSON)
    article_count = Column(Integer)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("instrument_id", "date", name="uq_company_risk_date"),
        Index("ix_company_risk_instrument_date", "instrument_id", "date"),
    )


# Phase 5: Geopolitical Risk History
class GeopoliticalRiskHistory(Base):
    __tablename__ = "geopolitical_risk_history"

    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    risk_score = Column(Float, nullable=False)
    sanctions_score = Column(Float)
    conflict_score = Column(Float)
    trade_war_score = Column(Float)
    diplomacy_score = Column(Float)
    components_json = Column(JSON)
    sources_json = Column(JSON)
    article_count = Column(Integer)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (UniqueConstraint("date", name="uq_geopolitical_risk_date"),)
