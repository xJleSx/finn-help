from __future__ import annotations

from enum import Enum
from typing import Callable, Optional

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from src.db.models import User
from src.interfaces.api.auth import AuthError, decode_token


class Role(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    TRADER = "trader"
    VIEWER = "viewer"


class Permission(str, Enum):
    VIEW_INSTRUMENTS = "view_instruments"
    VIEW_PORTFOLIO = "view_portfolio"
    TRADE_EXECUTE = "trade_execute"
    MANAGE_USERS = "manage_users"
    VIEW_ANALYSIS = "view_analysis"
    MANAGE_ALERTS = "manage_alerts"
    MANAGE_SYSTEM = "manage_system"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: {
        Permission.VIEW_INSTRUMENTS,
        Permission.VIEW_PORTFOLIO,
        Permission.TRADE_EXECUTE,
        Permission.MANAGE_USERS,
        Permission.VIEW_ANALYSIS,
        Permission.MANAGE_ALERTS,
        Permission.MANAGE_SYSTEM,
    },
    Role.ANALYST: {
        Permission.VIEW_INSTRUMENTS,
        Permission.VIEW_ANALYSIS,
        Permission.MANAGE_ALERTS,
    },
    Role.TRADER: {
        Permission.VIEW_INSTRUMENTS,
        Permission.VIEW_PORTFOLIO,
        Permission.TRADE_EXECUTE,
        Permission.VIEW_ANALYSIS,
        Permission.MANAGE_ALERTS,
    },
    Role.VIEWER: {
        Permission.VIEW_INSTRUMENTS,
        Permission.VIEW_PORTFOLIO,
        Permission.VIEW_ANALYSIS,
    },
}


def require_permission(permission: Permission) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        role = get_current_user_role(request)
        if role not in ROLE_PERMISSIONS:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unknown role")
        if permission not in ROLE_PERMISSIONS[role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission.value}",
            )

    return dependency


def get_current_user_role(request: Request, db_session: Optional[object] = None) -> Role:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = auth_header.removeprefix("Bearer ")
    try:
        payload = decode_token(token)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    role_str = payload.get("role", "viewer")
    try:
        role = Role(role_str)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Unknown role: {role_str}")

    if db_session is not None:
        user_id = int(payload.get("sub", 0))
        if user_id:
            user = db_session.execute(select(User).where(User.id == user_id, User.is_active)).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
            db_role_str = user.role
            if db_role_str != role_str:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Stale role — JWT says '{role_str}', DB says '{db_role_str}'",
                )

    return role
