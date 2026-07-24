from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth_service import (
    AuthService,
    _check_login_rate_limit,
    _validate_password,
)


@pytest.fixture
def mock_db():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def auth_service(mock_db):
    return AuthService(mock_db)


@pytest.fixture(autouse=True)
def clear_rate_limits():
    from src.core.auth_service import _LOGIN_ATTEMPTS
    _LOGIN_ATTEMPTS.clear()


class TestValidatePassword:
    def test_raises_on_short_password(self):
        with patch("src.core.auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 8
            with pytest.raises(HTTPException, match="at least 8 characters"):
                _validate_password("short")

    def test_passes_on_long_enough_password(self):
        with patch("src.core.auth_service.settings") as mock_settings:
            mock_settings.password_min_length = 8
            _validate_password("longenough")  # should not raise


class TestCheckLoginRateLimit:
    def test_allows_within_limit(self):
        key = "test_user"
        for _ in range(4):
            _check_login_rate_limit(key)  # should not raise

    def test_blocks_after_max_attempts(self):
        key = "test_user"
        for _ in range(5):
            _check_login_rate_limit(key)
        with pytest.raises(HTTPException, match="Too many login attempts"):
            _check_login_rate_limit(key)

    def test_expires_old_attempts(self):
        key = "test_user"
        now = datetime.now(timezone.utc).timestamp()
        from src.core.auth_service import _LOGIN_ATTEMPTS
        _LOGIN_ATTEMPTS[key] = [now - 400] * 5
        _check_login_rate_limit(key)
        assert len(_LOGIN_ATTEMPTS[key]) == 1


class TestRegister:
    async def test_register_success(self, auth_service, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        real_user = None

        async def _refresh(user):
            nonlocal real_user
            real_user = user
            user.id = 1

        mock_db.refresh = AsyncMock(side_effect=_refresh)

        with (
            patch("src.core.auth_service.hash_password", return_value="hashed_pw"),
            patch("src.core.auth_service.create_token", return_value="access"),
            patch("src.core.auth_service.create_refresh_token", return_value="refresh"),
        ):
            result = await auth_service.register("testuser", "password123")

        assert result["access_token"] == "access"
        assert result["refresh_token"] == "refresh"
        assert result["username"] == "testuser"

    async def test_register_duplicate_username(self, auth_service, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(HTTPException, match="already taken"):
            await auth_service.register("testuser", "password123")

    async def test_register_short_password_raises(self, auth_service):
        with pytest.raises(HTTPException, match="Password must be at least"):
            await auth_service.register("testuser", "short")


class TestLogin:
    async def test_login_success(self, auth_service, mock_db):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.hashed_password = "hashed"
        mock_user.totp_enabled = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with (
            patch("src.core.auth_service.verify_password", return_value=True),
            patch("src.core.auth_service.create_token", return_value="access"),
            patch("src.core.auth_service.create_refresh_token", return_value="refresh"),
        ):
            result = await auth_service.login("testuser", "password123")

        assert result["access_token"] == "access"
        assert result["username"] == "testuser"

    async def test_login_invalid_credentials(self, auth_service, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(HTTPException, match="Invalid credentials"):
            await auth_service.login("testuser", "wrongpass")

    async def test_login_totp_required(self, auth_service, mock_db):
        mock_user = MagicMock()
        mock_user.totp_enabled = True
        mock_user.hashed_password = "hashed"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("src.core.auth_service.verify_password", return_value=True):
            with pytest.raises(HTTPException, match="TOTP code required"):
                await auth_service.login("testuser", "password123")

    async def test_login_totp_invalid(self, auth_service, mock_db):
        mock_user = MagicMock()
        mock_user.totp_enabled = True
        mock_user.totp_secret = "secret"
        mock_user.recovery_codes = None
        mock_user.hashed_password = "hashed"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with (
            patch("src.core.auth_service.verify_password", return_value=True),
            patch("src.core.auth_service.verify_totp", return_value=False),
        ):
            with pytest.raises(HTTPException, match="Invalid TOTP code"):
                await auth_service.login("testuser", "password123", totp_code="000000")

    async def test_login_totp_valid(self, auth_service, mock_db):
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.totp_enabled = True
        mock_user.totp_secret = "secret"
        mock_user.recovery_codes = None
        mock_user.hashed_password = "hashed"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with (
            patch("src.core.auth_service.verify_password", return_value=True),
            patch("src.core.auth_service.verify_totp", return_value=True),
            patch("src.core.auth_service.create_token", return_value="access"),
            patch("src.core.auth_service.create_refresh_token", return_value="refresh"),
        ):
            result = await auth_service.login("testuser", "password123", totp_code="123456")
            assert result["access_token"] == "access"

    async def test_login_rate_limited(self, auth_service, mock_db):
        from datetime import datetime, timezone
        from src.core.auth_service import _LOGIN_ATTEMPTS
        now = datetime.now(timezone.utc).timestamp()
        _LOGIN_ATTEMPTS["testuser"] = [now] * 5
        with pytest.raises(HTTPException, match="Too many login attempts"):
            await auth_service.login("testuser", "password123")


class TestGetMe:
    async def test_returns_user_data(self, auth_service):
        user = MagicMock()
        user.id = 1
        user.username = "testuser"
        user.email = "test@example.com"
        user.role = "user"
        user.risk_profile = "balanced"
        user.totp_enabled = False
        user.is_active = True

        result = await auth_service.get_me(user)
        assert result["username"] == "testuser"
        assert result["email"] == "test@example.com"
        assert result["role"] == "user"

    async def test_handles_none_email(self, auth_service):
        user = MagicMock()
        user.email = None
        user.id = 1
        user.username = "test"
        user.role = "user"
        user.risk_profile = "balanced"
        user.totp_enabled = False
        user.is_active = True

        result = await auth_service.get_me(user)
        assert result["email"] is None


class TestSetupTOTP:
    async def test_setup_returns_secret_and_uri(self, auth_service, mock_db):
        user = MagicMock()
        with (
            patch("src.core.auth_service.generate_secret", return_value="NEWSECRET"),
            patch("src.core.auth_service.get_totp_uri", return_value="otpauth://..."),
        ):
            result = await auth_service.setup_totp(user)
        assert result["secret"] == "NEWSECRET"
        assert result["uri"] == "otpauth://..."
        assert user.totp_secret == "NEWSECRET"
        mock_db.commit.assert_called_once()


class TestConfirmTOTP:
    async def test_confirm_success(self, auth_service, mock_db):
        user = MagicMock()
        user.totp_secret = "secret"
        user.recovery_codes = None

        with (
            patch("src.core.auth_service.verify_totp", return_value=True),
            patch("src.core.auth_service.generate_recovery_codes", return_value=["c1", "c2"]),
            patch("src.core.auth_service.hash_recovery_code", return_value="hashed"),
        ):
            result = await auth_service.confirm_totp(user, "123456")

        assert result["enabled"] is True
        assert result["recovery_codes"] == ["c1", "c2"]
        assert user.totp_enabled is True
        assert mock_db.commit.called

    async def test_confirm_invalid_code(self, auth_service, mock_db):
        user = MagicMock()
        user.totp_secret = "secret"

        with patch("src.core.auth_service.verify_totp", return_value=False):
            with pytest.raises(HTTPException, match="Invalid TOTP code"):
                await auth_service.confirm_totp(user, "000000")


class TestDisableTOTP:
    async def test_disable_clears_fields(self, auth_service, mock_db):
        user = MagicMock()
        result = await auth_service.disable_totp(user)
        assert result["enabled"] is False
        assert user.totp_secret is None
        assert user.totp_enabled is False
        assert user.recovery_codes is None
        mock_db.commit.assert_called_once()
