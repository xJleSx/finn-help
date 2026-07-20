from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from .base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    resource = Column(String(200), nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    success = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now(), index=True)
