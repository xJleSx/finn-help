from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def patch_imports():
    modules_to_patch = [
        "src.analysis.service",
        "src.analysis.context",
        "src.analysis.fundamental",
        "src.market.service",
        "src.core.auth_service",
        "src.core.container",
        "src.notifications.service",
        "src.portfolio.service",
        "src.cache",
        "src.config",
    ]
    for mod in modules_to_patch:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    # Ensure config.settings exists with needed attrs
    class FakeSettings:
        jwt_secret = "test-secret"
        jwt_refresh_secret = "test-refresh-secret"
        jwt_expire_minutes = 15
        password_min_length = 8

    settings_mock = MagicMock()
    settings_mock.jwt_secret = "test-secret"
    settings_mock.jwt_refresh_secret = "test-refresh-secret"
    settings_mock.jwt_expire_minutes = 15
    settings_mock.password_min_length = 8
    sys.modules["src.config"].settings = settings_mock

    # Patch src.cache.get_redis
    sys.modules["src.cache"].get_redis = MagicMock(return_value=None)


class TestRolePermissionMapping:
    def test_admin_has_all_permissions(self):
        from src.interfaces.api.rbac.models import ROLE_PERMISSIONS, Permission, Role

        expected = {
            Permission.VIEW_INSTRUMENTS,
            Permission.VIEW_PORTFOLIO,
            Permission.TRADE_EXECUTE,
            Permission.MANAGE_USERS,
            Permission.VIEW_ANALYSIS,
            Permission.MANAGE_ALERTS,
            Permission.MANAGE_SYSTEM,
        }
        assert ROLE_PERMISSIONS[Role.ADMIN] == expected

    def test_viewer_has_limited_permissions(self):
        from src.interfaces.api.rbac.models import ROLE_PERMISSIONS, Permission, Role

        assert Permission.TRADE_EXECUTE not in ROLE_PERMISSIONS[Role.VIEWER]
        assert Permission.MANAGE_USERS not in ROLE_PERMISSIONS[Role.VIEWER]
        assert Permission.VIEW_INSTRUMENTS in ROLE_PERMISSIONS[Role.VIEWER]

    def test_trader_can_trade_cannot_manage_users(self):
        from src.interfaces.api.rbac.models import ROLE_PERMISSIONS, Permission, Role

        assert Permission.TRADE_EXECUTE in ROLE_PERMISSIONS[Role.TRADER]
        assert Permission.MANAGE_USERS not in ROLE_PERMISSIONS[Role.TRADER]

    def test_analyst_cannot_trade(self):
        from src.interfaces.api.rbac.models import ROLE_PERMISSIONS, Permission, Role

        assert Permission.TRADE_EXECUTE not in ROLE_PERMISSIONS[Role.ANALYST]
        assert Permission.VIEW_ANALYSIS in ROLE_PERMISSIONS[Role.ANALYST]

    def test_unknown_role_not_in_mapping(self):
        from src.interfaces.api.rbac.models import ROLE_PERMISSIONS

        assert b"unknown" not in [r.value for r in ROLE_PERMISSIONS]


class TestGetCurrentUserRole:
    def test_returns_role_from_jwt(self):
        from src.interfaces.api.rbac.models import Role, get_current_user_role

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer valid.jwt.token"}

        with patch("src.interfaces.api.rbac.models.decode_token", return_value={"role": "admin"}):
            assert get_current_user_role(mock_request) == Role.ADMIN

    def test_returns_viewer_when_no_role_in_jwt(self):
        from src.interfaces.api.rbac.models import Role, get_current_user_role

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer token"}

        with patch("src.interfaces.api.rbac.models.decode_token", return_value={}):
            assert get_current_user_role(mock_request) == Role.VIEWER

    def test_raises_on_missing_auth_header(self):
        from fastapi import HTTPException

        from src.interfaces.api.rbac.models import get_current_user_role

        mock_request = MagicMock()
        mock_request.headers = {}

        with pytest.raises(HTTPException) as exc:
            get_current_user_role(mock_request)
        assert exc.value.status_code == 401

    def test_raises_on_invalid_role(self):
        from fastapi import HTTPException

        from src.interfaces.api.rbac.models import get_current_user_role

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer token"}

        with patch("src.interfaces.api.rbac.models.decode_token", return_value={"role": "superadmin"}):
            with pytest.raises(HTTPException) as exc:
                get_current_user_role(mock_request)
            assert exc.value.status_code == 403


class TestRequirePermission:
    def test_allows_admin_with_permission(self):
        from src.interfaces.api.rbac.models import Permission, require_permission

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer token"}

        with patch("src.interfaces.api.rbac.models.decode_token", return_value={"role": "admin"}):
            check = require_permission(Permission.MANAGE_SYSTEM)
            check(mock_request)

    def test_denies_viewer_trade_execute(self):
        from fastapi import HTTPException

        from src.interfaces.api.rbac.models import Permission, require_permission

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer token"}

        with patch("src.interfaces.api.rbac.models.decode_token", return_value={"role": "viewer"}):
            check = require_permission(Permission.TRADE_EXECUTE)
            with pytest.raises(HTTPException) as exc:
                check(mock_request)
            assert exc.value.status_code == 403

    def test_denies_analyst_trade_execute(self):
        from fastapi import HTTPException

        from src.interfaces.api.rbac.models import Permission, require_permission

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer token"}

        with patch("src.interfaces.api.rbac.models.decode_token", return_value={"role": "analyst"}):
            check = require_permission(Permission.TRADE_EXECUTE)
            with pytest.raises(HTTPException) as exc:
                check(mock_request)
            assert exc.value.status_code == 403

    def test_allows_trader_trade_execute(self):
        from src.interfaces.api.rbac.models import Permission, require_permission

        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer token"}

        with patch("src.interfaces.api.rbac.models.decode_token", return_value={"role": "trader"}):
            check = require_permission(Permission.TRADE_EXECUTE)
            check(mock_request)


class TestAuditLogQuery:
    @patch("src.interfaces.api.rbac.audit.get_session")
    def test_log_creates_entry(self, mock_get_session):
        from src.interfaces.api.rbac.audit import AuditTrail

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        mock_get_session.return_value = mock_db

        AuditTrail.log(user_id="1", action="test_action", resource="test:123", details="test", ip_address="127.0.0.1")

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("src.interfaces.api.rbac.audit.get_session")
    def test_log_rolls_back_on_error(self, mock_get_session):
        from src.interfaces.api.rbac.audit import AuditTrail

        mock_db = MagicMock()
        mock_db.add.side_effect = Exception("DB error")
        mock_get_session.return_value = mock_db

        with pytest.raises(Exception):
            AuditTrail.log(user_id="1", action="test", resource="test:123")

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("src.interfaces.api.rbac.audit.get_session")
    def test_query_returns_list(self, mock_get_session):
        from src.interfaces.api.rbac.audit import AuditTrail

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        mock_get_session.return_value = mock_db

        result = AuditTrail.query()
        assert result == []
        mock_db.close.assert_called_once()

    @patch("src.interfaces.api.rbac.audit.get_session")
    def test_get_user_activity(self, mock_get_session):
        from datetime import datetime, timezone

        from src.interfaces.api.rbac.audit import AuditTrail

        mock_db = MagicMock()
        mock_entry = MagicMock()
        mock_entry.id = 1
        mock_entry.user_id = "1"
        mock_entry.action = "login"
        mock_entry.resource = "auth"
        mock_entry.details = None
        mock_entry.ip_address = "127.0.0.1"
        mock_entry.success = True
        mock_entry.created_at = datetime.now(timezone.utc)
        mock_db.execute.return_value.scalars.return_value.all.return_value = [mock_entry]
        mock_get_session.return_value = mock_db

        result = AuditTrail.get_user_activity(user_id="1", days=7)
        assert len(result) == 1
        assert result[0]["action"] == "login"
        assert result[0]["success"] is True

    @patch("src.interfaces.api.rbac.audit.get_session")
    def test_query_filters_by_action(self, mock_get_session):
        from src.interfaces.api.rbac.audit import AuditTrail

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        mock_get_session.return_value = mock_db

        AuditTrail.query(action="execute_order")
        mock_db.close.assert_called_once()


class TestOAuthLoginFlow:
    @pytest.mark.asyncio
    async def test_oauth_creates_user(self):
        from src.interfaces.api.auth import oauth_login

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.interfaces.api.auth.get_session", return_value=mock_db):
            with patch("src.interfaces.api.auth._verify_oauth_code") as mock_verify:
                mock_verify.return_value = {"id": "google_test", "email": "test@google.com"}
                result = await oauth_login(provider="google", code="valid_code_123")
        assert "access_token" in result
        assert result["token_type"] == "bearer"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_oauth_returns_existing_user(self):
        from src.interfaces.api.auth import oauth_login

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.username = "existing_user"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_user

        with patch("src.interfaces.api.auth.get_session", return_value=mock_db):
            with patch("src.interfaces.api.auth._verify_oauth_code") as mock_verify:
                mock_verify.return_value = {"id": "github_test", "email": "test@github.com"}
                result = await oauth_login(provider="github", code="existing_code")
        assert "access_token" in result
        assert result["user_id"] == 42

    @pytest.mark.asyncio
    async def test_oauth_empty_code_raises(self):
        from src.interfaces.api.auth import oauth_login

        with pytest.raises(Exception):
            await oauth_login(provider="google", code="")

    def test_create_oauth_token_returns_string(self):
        from src.interfaces.api.auth import create_oauth_token

        token = create_oauth_token(provider="google", provider_user_id="123", email="user@example.com")
        assert isinstance(token, str)
        assert len(token) > 20
