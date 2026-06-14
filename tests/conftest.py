"""Test configuration: temporary SQLite file with all tables"""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base


@pytest.fixture(scope="session")
def in_memory_db():
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = db_file.name
    db_file.close()
    engine = create_engine(f"sqlite:///{db_path}", echo=False, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    try:
        os.unlink(db_path)
    except PermissionError:
        pass


@pytest.fixture
def db_session(in_memory_db):
    session_class = sessionmaker(bind=in_memory_db)
    session = session_class()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    from src.interfaces.api.server import app, get_db

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    from fastapi.testclient import TestClient

    yield TestClient(app)
    app.dependency_overrides.clear()
