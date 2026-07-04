from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.alerts.preferences import UserAlertPreferences
from src.db.connection import get_session
from src.db.models import User
from src.interfaces.api.auth import require_user
from src.interfaces.api.schemas import AlertPreferencesResponse

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["alert-preferences"])


def _sync_get_prefs(user_id: int) -> dict[str, Any]:
    db = get_session()
    try:
        prefs = UserAlertPreferences()
        return prefs.get_preferences(user_id, db)
    finally:
        db.close()


def _sync_set_prefs(user_id: int, body: dict[str, Any]) -> dict[str, Any]:
    db = get_session()
    try:
        prefs = UserAlertPreferences()
        kwargs = {}
        if "min_severity" in body:
            kwargs["min_severity"] = body["min_severity"]
        if "quiet_hours_start" in body:
            kwargs["quiet_hours_start"] = body["quiet_hours_start"]
        if "quiet_hours_end" in body:
            kwargs["quiet_hours_end"] = body["quiet_hours_end"]
        prefs.set_preferences(user_id, db, **kwargs)
        return prefs.get_preferences(user_id, db)
    finally:
        db.close()


def _sync_mute_ticker(user_id: int, ticker: str) -> bool:
    db = get_session()
    try:
        prefs = UserAlertPreferences()
        return prefs.mute_ticker(user_id, ticker, db)
    finally:
        db.close()


def _sync_unmute_ticker(user_id: int, ticker: str) -> bool:
    db = get_session()
    try:
        prefs = UserAlertPreferences()
        return prefs.unmute_ticker(user_id, ticker, db)
    finally:
        db.close()


@router.get("/api/alert-preferences", response_model=AlertPreferencesResponse)
async def get_alert_preferences(
    user: User = Depends(require_user),
) -> dict[str, Any]:
    import asyncio

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _sync_get_prefs, user.id)
    except Exception as e:
        logger.exception("alert_prefs_get_failed", user_id=user.id)
        raise HTTPException(500, f"Failed to get alert preferences: {e}")


class UpdateAlertPreferencesBody(BaseModel):
    min_severity: str | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None


@router.put("/api/alert-preferences", response_model=AlertPreferencesResponse)
async def update_alert_preferences(
    body: UpdateAlertPreferencesBody,
    user: User = Depends(require_user),
) -> dict[str, Any]:
    import asyncio

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _sync_set_prefs, user.id, body.model_dump(exclude_none=True))
    except Exception as e:
        logger.exception("alert_prefs_update_failed", user_id=user.id)
        raise HTTPException(500, f"Failed to update alert preferences: {e}")


@router.post("/api/alert-preferences/mute/{ticker}")
async def mute_ticker(
    ticker: str,
    user: User = Depends(require_user),
) -> dict[str, str]:
    import asyncio

    loop = asyncio.get_running_loop()
    try:
        ok = await loop.run_in_executor(None, _sync_mute_ticker, user.id, ticker)
        if not ok:
            return {"status": "already_muted"}
        return {"status": "ok"}
    except Exception as e:
        logger.exception("alert_prefs_mute_failed", user_id=user.id, ticker=ticker)
        raise HTTPException(500, f"Failed to mute ticker: {e}")


@router.post("/api/alert-preferences/unmute/{ticker}")
async def unmute_ticker(
    ticker: str,
    user: User = Depends(require_user),
) -> dict[str, str]:
    import asyncio

    loop = asyncio.get_running_loop()
    try:
        ok = await loop.run_in_executor(None, _sync_unmute_ticker, user.id, ticker)
        if not ok:
            return {"status": "not_found"}
        return {"status": "ok"}
    except Exception as e:
        logger.exception("alert_prefs_unmute_failed", user_id=user.id, ticker=ticker)
        raise HTTPException(500, f"Failed to unmute ticker: {e}")
