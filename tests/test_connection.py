"""Tests for DB connection (extended)"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestSession:
    def test_get_session(self):
        from src.db.connection import get_session

        session = get_session()
        assert session is not None
        session.close()

    def test_get_session_lifecycle(self):
        from src.db.connection import close_session, get_session

        s1 = get_session()
        assert s1 is not None
        s1.close()
        close_session()

    def test_close_session_noop(self):
        from src.db.connection import close_session

        close_session()


class TestInitDb:
    def test_init_db_calls_alembic(self):
        with (
            patch("alembic.command.upgrade") as mock_upgrade,
            patch("alembic.config.Config"),
        ):
            from src.db.connection import init_db

            init_db()
            mock_upgrade.assert_called_once()


class TestGetAsyncSession:
    @pytest.mark.asyncio
    async def test_yields_session_and_commits(self):
        with patch("src.db.connection.AsyncSessionLocal") as mock_session_local:
            mock_session = AsyncMock()
            mock_session_local.return_value.__aenter__.return_value = mock_session

            from src.db.connection import get_async_session

            gen = get_async_session()
            session = await gen.__anext__()
            assert session is mock_session

            try:
                await gen.__anext__()
            except StopAsyncIteration:
                pass

            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_on_error(self):
        with patch("src.db.connection.AsyncSessionLocal") as mock_session_local:
            mock_session = AsyncMock()
            mock_session_local.return_value.__aenter__.return_value = mock_session

            from src.db.connection import get_async_session

            gen = get_async_session()
            session = await gen.__anext__()
            assert session is mock_session

            with pytest.raises(RuntimeError):
                await gen.athrow(RuntimeError("test error"))

            mock_session.rollback.assert_awaited_once()
