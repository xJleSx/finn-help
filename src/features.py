from __future__ import annotations

import logging

from sqlalchemy import select

from src.db.connection import get_session
from src.db.models.feature_flag import FeatureFlag

logger = logging.getLogger(__name__)


def is_enabled(name: str, default: bool = False) -> bool:
    try:
        db = get_session()
        try:
            result = db.execute(select(FeatureFlag).where(FeatureFlag.name == name))
            flag = result.scalars().first()
            return flag.enabled if flag else default
        finally:
            db.close()
    except Exception as e:
        logger.warning("Feature flag check failed for %s: %s", name, e)
        return default


def set_flag(name: str, enabled: bool, description: str = "") -> None:
    try:
        db = get_session()
        try:
            result = db.execute(select(FeatureFlag).where(FeatureFlag.name == name))
            flag = result.scalars().first()
            if flag:
                flag.enabled = enabled
                if description:
                    flag.description = description
            else:
                db.add(FeatureFlag(name=name, enabled=enabled, description=description))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Feature flag set failed for %s: %s", name, e)


def list_flags() -> list[dict[str, object]]:
    try:
        db = get_session()
        try:
            result = db.execute(select(FeatureFlag).order_by(FeatureFlag.name))
            return [
                {
                    "name": f.name,
                    "enabled": f.enabled,
                    "description": f.description or "",
                    "updated_at": str(f.updated_at) if f.updated_at else "",
                }
                for f in result.scalars().all()
            ]
        finally:
            db.close()
    except Exception as e:
        logger.warning("Feature flag list failed: %s", e)
        return []
