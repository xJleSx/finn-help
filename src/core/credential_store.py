from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.crypto import CryptoError
from src.db.models.user import BrokerCredential

logger = logging.getLogger(__name__)

_BROKER_TOKEN_ATTRS: dict[str, str] = {
    "tbank": "tinkoff_token",
    "bcs": "bcs_refresh_token",
    "alor": "alor_token",
    "openapi": "openapi_token",
}


def get_broker_token(user_id: int, broker_name: str, db: Session | None = None) -> str | None:
    if db is not None:
        try:
            result = db.execute(
                select(BrokerCredential)
                .where(
                    BrokerCredential.user_id == user_id,
                    BrokerCredential.broker_name == broker_name,
                    BrokerCredential.is_active == True,
                )
                .order_by(BrokerCredential.updated_at.desc())
                .limit(1)
            )
            cred = result.scalar_one_or_none()
            if cred is not None:
                return cred.get_token()
        except CryptoError:
            raise
        except Exception as e:
            logger.warning("Failed to read broker credential from DB: %s", e)

    from src.config import settings

    attr = _BROKER_TOKEN_ATTRS.get(broker_name.lower())
    if attr and hasattr(settings, attr):
        val = getattr(settings, attr, None)
        if val:
            return str(val)
    return None


def set_broker_token(user_id: int, broker_name: str, token: str, db: Session) -> None:
    result = db.execute(
        select(BrokerCredential).where(
            BrokerCredential.user_id == user_id,
            BrokerCredential.broker_name == broker_name,
        )
    )
    cred = result.scalar_one_or_none()
    if cred is None:
        cred = BrokerCredential(user_id=user_id, broker_name=broker_name.lower())
        db.add(cred)
    cred.set_token(token)
    cred.is_active = True
    db.commit()
    logger.info("Broker credential stored for user %d / %s", user_id, broker_name)


def delete_broker_token(user_id: int, broker_name: str, db: Session) -> bool:
    result = db.execute(
        select(BrokerCredential).where(
            BrokerCredential.user_id == user_id,
            BrokerCredential.broker_name == broker_name,
        )
    )
    cred = result.scalar_one_or_none()
    if cred is None:
        return False
    db.delete(cred)
    db.commit()
    logger.info("Broker credential deleted for user %d / %s", user_id, broker_name)
    return True


def list_broker_tokens(user_id: int, db: Session) -> list[dict[str, Any]]:
    result = db.execute(
        select(BrokerCredential).where(
            BrokerCredential.user_id == user_id,
        )
    )
    return [
        {
            "broker_name": cred.broker_name,
            "token_type": cred.token_type,
            "is_active": cred.is_active,
            "created_at": str(cred.created_at) if cred.created_at else None,
            "updated_at": str(cred.updated_at) if cred.updated_at else None,
            "has_token": bool(cred.token_encrypted),
        }
        for cred in result.scalars().all()
    ]
