from __future__ import annotations

from typing import Any

import structlog
from fastapi import Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User
from src.interfaces.api.auth import create_token, get_db, hash_password, verify_password

logger = structlog.get_logger(__name__)


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(self, username: str, password: str, email: str | None = None, risk_profile: str = "balanced") -> dict[str, Any]:
        filters = [User.username == username]
        if email is not None:
            filters.append(User.email == email)
        result = await self.db.execute(
            select(User).where(or_(*filters))
        )
        if result.scalar_one_or_none():
            raise HTTPException(400, "Username or email already taken")
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            risk_profile=risk_profile or "balanced",
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        token = create_token(int(user.id), str(user.username))
        return {"access_token": token, "token_type": "bearer", "user_id": int(user.id), "username": str(user.username)}

    async def login(self, username: str, password: str) -> dict[str, Any]:
        result = await self.db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, str(user.hashed_password)):
            raise HTTPException(401, "Invalid credentials")
        token = create_token(int(user.id), str(user.username))
        return {"access_token": token, "token_type": "bearer", "user_id": int(user.id), "username": str(user.username)}

    async def get_me(self, user: User) -> dict[str, Any]:
        return {
            "id": int(user.id),
            "username": str(user.username),
            "email": str(user.email) if user.email is not None else None,
            "role": str(user.role),
            "risk_profile": str(user.risk_profile),
            "is_active": bool(user.is_active),
        }
