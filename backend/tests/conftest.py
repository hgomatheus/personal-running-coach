"""
Shared pytest fixtures for the Personal Running Coach test suite.

Provides:
  - in-memory SQLite engine / session
  - FastAPI dependency override for get_db
  - Synchronous TestClient fixture
  - Async httpx.AsyncClient fixture
  - Pre-seeded Profile (id=1, id=2) and AppSettings rows
"""

import os

# Set the test database URL BEFORE importing any app modules so that
# app.database.engine is created pointing at the in-memory SQLite DB.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
import pytest_asyncio
from unittest.mock import patch
from httpx import AsyncClient, ASGITransport
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.orm import Base, Profile, AppSettings
from app.database import get_db
from app.main import app

# ---------------------------------------------------------------------------
# In-memory SQLite engine (shared across the test session)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


# ---------------------------------------------------------------------------
# Session-scoped DB setup: create tables + seed rows once per test session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create all ORM tables and seed initial data for the test session."""
    Base.metadata.create_all(bind=test_engine)
    _seed(TestSessionLocal())
    yield
    Base.metadata.drop_all(bind=test_engine)


def _seed(db):
    try:
        if not db.query(Profile).filter(Profile.id == 1).first():
            db.add(Profile(id=1, display_name="Profile 1"))
        if not db.query(Profile).filter(Profile.id == 2).first():
            db.add(Profile(id=2, display_name="Profile 2"))
        if not db.query(AppSettings).filter(AppSettings.id == 1).first():
            db.add(AppSettings(
                id=1,
                strava_sync_interval_minutes=15,
                backup_enabled=True,
                backup_retention_days=30,
            ))
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Per-test DB session fixture with dependency override
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    """Yield a test database session and roll back after each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    def override_get_db():
        try:
            yield session
        finally:
            pass  # cleanup handled below

    app.dependency_overrides[get_db] = override_get_db

    yield session

    app.dependency_overrides.pop(get_db, None)
    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Synchronous TestClient
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(db_session):
    """Synchronous FastAPI TestClient with the test DB wired in.

    Patches start_scheduler, stop_scheduler, and IPFilterMiddleware so the
    test client can make requests without being blocked by the IP filter.
    """
    with (
        patch("app.main.start_scheduler"),
        patch("app.main.stop_scheduler"),
        patch("app.middleware.ip_filter.IPFilterMiddleware.dispatch",
              new=lambda self, request, call_next: call_next(request)),
        TestClient(app, raise_server_exceptions=True) as c,
    ):
        yield c


# ---------------------------------------------------------------------------
# Async httpx.AsyncClient
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def async_client(db_session):
    """Async httpx.AsyncClient backed by the FastAPI ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
