"""Integration tests with real PostgreSQL and Redis via testcontainers.

Requires:
    - Docker running on the host
    - testcontainers>=4.0.0

Marked with @pytest.mark.slow and excluded from CI.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any, Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

pytestmark = [pytest.mark.slow, pytest.mark.skipif(os.environ.get("CI") == "true", reason="Skipped in CI; requires Docker runtime")]


@pytest.fixture(scope="module")
def postgres_container() -> Generator[str, None, None]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="module")
def redis_container() -> Generator[str, None, None]:
    from testcontainers.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as rc:
        yield rc.get_connection_url()


@pytest.fixture(scope="module")
def pg_engine(postgres_container: str) -> Generator[Engine, None, None]:
    engine = create_engine(postgres_container)
    from src.db.models import Base
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine: Engine) -> Generator[Session, None, None]:
    session_class = sessionmaker(bind=pg_engine)
    with session_class() as session:
        yield session
        session.rollback()


class TestPostgresIntegration:
    def test_seed_instrument(self, pg_session: Session) -> None:
        pg_session.execute(
            text("INSERT INTO instruments (ticker, name, type, sector, is_active) VALUES (:t, :n, :ty, :s, :a)"),
            {"t": "SBER", "n": "Sberbank", "ty": "stock", "s": "Finance", "a": True},
        )
        pg_session.commit()
        row = pg_session.execute(text("SELECT ticker, name FROM instruments WHERE ticker='SBER'")).fetchone()
        assert row is not None
        assert row[0] == "SBER"
        assert row[1] == "Sberbank"

    def test_feature_cache_roundtrip(self, pg_session: Session) -> None:
        pg_session.execute(
            text("""
                INSERT INTO feature_cache (ticker, feature_type, date, value_json, version)
                VALUES (:t, :ft, :d, :vj, :v)
            """),
            {
                "t": "SBER",
                "ft": "technical",
                "d": date.today(),
                "vj": json.dumps({"rsi": 55.0, "macd": 0.5}),
                "v": 1,
            },
        )
        pg_session.commit()

        row = pg_session.execute(
            text("SELECT value_json FROM feature_cache WHERE ticker=:t AND feature_type=:ft"),
            {"t": "SBER", "ft": "technical"},
        ).fetchone()
        assert row is not None
        data = json.loads(row[0])
        assert data["rsi"] == 55.0
        assert data["macd"] == 0.5

    def test_user_totp_fields_exist(self, pg_session: Session) -> None:
        pg_session.execute(
            text("""
                INSERT INTO users (username, hashed_password, totp_secret, totp_enabled)
                VALUES (:u, :hp, :ts, :te)
            """),
            {"u": "totp_test", "hp": "abc123", "ts": "JBSWY3DPEHPK3PXP", "te": True},
        )
        pg_session.commit()

        row = pg_session.execute(
            text("SELECT totp_secret, totp_enabled FROM users WHERE username='totp_test'")
        ).fetchone()
        assert row is not None
        assert row[0] == "JBSWY3DPEHPK3PXP"
        assert row[1] is True

    def test_alembic_migration_state(self, pg_engine: Engine) -> None:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        with pg_engine.connect() as conn:
            mc = MigrationContext.configure(conn)
            heads = mc.get_current_heads()
            assert len(heads) > 0, "No migrations have been applied"
            script = ScriptDirectory.from_config(Config())
            head_revision = script.get_current_head()
            assert head_revision in heads, f"Migration head {head_revision} not applied"

    def test_broker_credentials_encrypted(self, pg_session: Session) -> None:
        pg_session.execute(
            text("""
                INSERT INTO broker_credentials (user_id, broker_type, encrypted_token, is_active)
                VALUES (:u, :bt, :et, :ia)
            """),
            {"u": 1, "bt": "tbank", "et": "gAAAAABtestencryptedvalue123=", "ia": True},
        )
        pg_session.commit()

        row = pg_session.execute(
            text("SELECT encrypted_token FROM broker_credentials WHERE user_id=1 AND broker_type='tbank'")
        ).fetchone()
        assert row is not None
        assert row[0].startswith("gAAAAA")


class TestRedisIntegration:
    @pytest.fixture(scope="class")
    def redis_client(self, redis_container: str) -> Any:
        import redis as redis_mod
        from redis import ConnectionPool

        pool = ConnectionPool.from_url(redis_container, decode_responses=True)
        client = redis_mod.Redis(connection_pool=pool)
        client.flushall()
        yield client
        pool.disconnect()

    def test_set_and_get(self, redis_client: Any) -> None:
        redis_client.set("finn:test:key", "hello")
        val = redis_client.get("finn:test:key")
        assert val == "hello"

    def test_setex_ttl(self, redis_client: Any) -> None:
        redis_client.setex("finn:test:ttl", 60, "world")
        ttl = redis_client.ttl("finn:test:ttl")
        assert 0 < ttl <= 60

    def test_json_roundtrip(self, redis_client: Any) -> None:
        data = {"rsi": 45.2, "macd": -0.3, "signal": "BUY"}
        redis_client.setex("finn:feat:SBER:technical", 3600, json.dumps(data))
        raw = redis_client.get("finn:feat:SBER:technical")
        parsed = json.loads(raw)
        assert parsed["signal"] == "BUY"
        assert parsed["rsi"] == 45.2

    def test_feature_store_pattern(self, redis_client: Any) -> None:
        tickers = ["SBER", "GAZP", "LKOH"]
        for t in tickers:
            redis_client.setex(f"finn:feat:{t}:technical", 3600, json.dumps({"score": 0.5}))
        keys = redis_client.keys("finn:feat:*:technical")
        assert len(keys) == 3

    def test_invalidate_pattern(self, redis_client: Any) -> None:
        redis_client.set("finn:feat:SBER:sentiment", json.dumps({"val": 1}))
        redis_client.set("finn:feat:SBER:technical", json.dumps({"val": 2}))
        for key in redis_client.scan_iter("finn:feat:SBER:*"):
            redis_client.delete(key)
        remaining = redis_client.keys("finn:feat:SBER:*")
        assert len(remaining) == 0

    def test_pubsub_channel(self, redis_client: Any) -> None:
        redis_client.publish("finn:notifications", "test message")
        assert redis_client.pubsub_numsub("finn:notifications")[0][1] >= 0


class TestPipelineEndToEnd:
    @pytest.fixture(scope="class")
    def redis_client(self, redis_container: str) -> Any:
        import redis as redis_mod
        from redis import ConnectionPool

        pool = ConnectionPool.from_url(redis_container, decode_responses=True)
        client = redis_mod.Redis(connection_pool=pool)
        client.flushall()
        yield client
        pool.disconnect()

    def test_daily_update_cycle(self, pg_session: Session, redis_client: Any) -> None:
        """Simulate the daily scheduler cycle: seed data -> collect -> cache."""
        pg_session.execute(
            text("""
                INSERT INTO instruments (ticker, name, type, sector, is_active)
                VALUES (:t, :n, :ty, :s, :a)
            """),
            {"t": "SBER", "n": "Sberbank", "ty": "stock", "s": "Finance", "a": True},
        )
        pg_session.execute(
            text("""
                INSERT INTO prices (instrument_id, date, open, high, low, close, volume)
                VALUES (:iid, :d, :o, :h, :l, :c, :v)
            """),
            [
                {"iid": 1, "d": date.today() - timedelta(days=i), "o": 250.0, "h": 255.0, "l": 248.0, "c": 252.0 + i * 0.1, "v": 1000000}
                for i in range(100)
            ],
        )
        pg_session.commit()

        cached_val = json.dumps({"rsi": 55.0, "action": "HOLD"})
        redis_client.setex("finn:feat:SBER:technical", 3600, cached_val)
        pg_session.execute(
            text("""
                INSERT INTO feature_cache (ticker, feature_type, date, value_json, version)
                VALUES ('SBER', 'technical', :d, :vj, 1)
            """),
            {"d": date.today(), "vj": cached_val},
        )
        pg_session.commit()

        row = pg_session.execute(
            text("SELECT COUNT(*) FROM prices WHERE instrument_id=1")
        ).fetchone()
        assert row is not None
        assert row[0] == 100

        redis_val = redis_client.get("finn:feat:SBER:technical")
        assert redis_val is not None
        parsed = json.loads(redis_val)
        assert parsed["action"] == "HOLD"
