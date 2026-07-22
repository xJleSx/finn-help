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
    prev_hash = Column(String(64), nullable=True)
    hash = Column(String(64), nullable=True, unique=True)

    @staticmethod
    def validate_chain(entries: list["AuditLog"]) -> list[dict]:
        """Validate the hash chain of audit log entries. Returns list of issues found."""
        issues: list[dict] = []
        prev = ""
        for entry in entries:
            if entry.prev_hash != prev:
                issues.append({"id": entry.id, "issue": "chain_break", "expected_prev": prev, "got": entry.prev_hash})
            import hashlib
            computed = hashlib.sha256(str(entry.__dict__.get("details", "")).encode()).hexdigest()[:16]
            if entry.hash and not computed.startswith(entry.hash[:16]):
                issues.append({"id": entry.id, "issue": "hash_mismatch"})
            prev = entry.hash or ""
        return issues
