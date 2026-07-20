from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from src.db.connection import get_session
from src.db.models.audit import AuditLog


class AuditTrail:
    @staticmethod
    def log(
        user_id: str,
        action: str,
        resource: str,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
        success: bool = True,
    ) -> None:
        db = get_session()
        try:
            entry = AuditLog(
                user_id=str(user_id),
                action=action,
                resource=resource,
                details=details,
                ip_address=ip_address,
                success=success,
            )
            db.add(entry)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def query(
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        db = get_session()
        try:
            stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
            if user_id:
                stmt = stmt.where(AuditLog.user_id == str(user_id))
            if action:
                stmt = stmt.where(AuditLog.action == action)
            results = db.execute(stmt.limit(limit)).scalars().all()
            return [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "action": r.action,
                    "resource": r.resource,
                    "details": r.details,
                    "ip_address": r.ip_address,
                    "success": r.success,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in results
            ]
        finally:
            db.close()

    @staticmethod
    def get_user_activity(user_id: str, days: int = 30) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        db = get_session()
        try:
            stmt = (
                select(AuditLog)
                .where(AuditLog.user_id == str(user_id), AuditLog.created_at >= cutoff)
                .order_by(AuditLog.created_at.desc())
            )
            results = db.execute(stmt).scalars().all()
            return [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "action": r.action,
                    "resource": r.resource,
                    "details": r.details,
                    "ip_address": r.ip_address,
                    "success": r.success,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in results
            ]
        finally:
            db.close()
