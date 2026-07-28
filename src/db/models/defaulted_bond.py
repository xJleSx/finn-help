
from sqlalchemy import Column, Date, Float, Integer, String

from .base import Base


class DefaultedBond(Base):
    __tablename__ = "defaulted_bonds"

    id = Column(Integer, primary_key=True)
    isin = Column(String(12), unique=True, nullable=False, index=True)
    ticker = Column(String(20), nullable=False)
    issuer = Column(String(255), nullable=False)
    default_date = Column(Date, nullable=False)
    recovery_rate = Column(Float, default=0.0)
    rating_before = Column(String(10))
    rating_after = Column(String(10))
    source = Column(String(50), default="manual")
