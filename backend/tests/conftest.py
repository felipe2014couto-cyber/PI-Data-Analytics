"""Test configuration and fixtures."""
import os
import sys
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB_PATH = ROOT / "tests" / "_test_pads.db"
if TEST_DB_PATH.exists():
    try:
        TEST_DB_PATH.unlink()
    except OSError:
        pass

os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("PI_WEB_API_BASE_URL", "")
os.environ.setdefault("PI_DATA_SERVER_NAME", "")
os.environ.setdefault("AUTH_JWT_SECRET", "test-only-secret-that-is-at-least-thirty-two-characters")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.api import deps  # noqa: E402
from app.api.deps import get_db_session, get_pi_provider, get_pi_service  # noqa: E402
from app.database.session import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402,E401
    Equipment,
    PiTag,
    PiTagDataType,
    PiTagValidationStatus,
    Section,
    VariableType,
    User,
    UserRole,
)
from app.api.deps import get_current_user, validate_csrf  # noqa: E402
from app.services.pi_service import PiService  # noqa: E402
from tests.pi_fakes import FakePiDataProvider  # noqa: E402

engine = create_engine(
    os.environ["DATABASE_URL"],
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


def _override_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def fake_provider():
    return FakePiDataProvider()


@pytest.fixture()
def client(fake_provider):
    app = create_app()

    def _db_override():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _provider_override():
        return fake_provider

    def _service_override(
        db=Depends(_db_override),
        provider=Depends(_provider_override),
    ):
        return PiService(db, provider=provider)

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_db_session] = _db_override
    app.dependency_overrides[get_pi_provider] = _provider_override
    app.dependency_overrides[get_pi_service] = _service_override
    def _authenticated_user():
        db = TestingSessionLocal()
        try:
            user = db.query(User).filter(User.normalized_username == "test-admin").first()
            if not user:
                user = User(username="test-admin", normalized_username="test-admin", password_hash="test-hash", role=UserRole.ADMIN, is_active=True, auth_version=1, must_change_password=False)
                db.add(user); db.commit(); db.refresh(user)
            db.expunge(user)
            return user
        finally: db.close()
    app.dependency_overrides[get_current_user] = _authenticated_user
    app.dependency_overrides[validate_csrf] = lambda: None

    with TestClient(app, backend_options={"use_uvloop": True}) as c:
        c.fake_provider = fake_provider  # type: ignore[attr-defined]
        yield c


@pytest.fixture(autouse=True)
def _clean_tables(db_session):
    for table in reversed(Base.metadata.sorted_tables):
        db_session.execute(table.delete())
    db_session.commit()
    yield


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Reset the cached settings instance and refresh every module that
    imported ``settings`` from ``app.core.config`` so service code keeps
    using the most recent object."""
    import app.core.config as config_module
    import sys

    modules_with_settings = [
        name
        for name, module in sys.modules.items()
        if module is not None
        and hasattr(module, "settings")
        and getattr(module, "settings", None) is config_module.settings
    ]

    get_settings.cache_clear()
    new_settings = get_settings()
    config_module.settings = new_settings
    for name in modules_with_settings:
        setattr(sys.modules[name], "settings", new_settings)
    yield
    get_settings.cache_clear()
    new_settings = get_settings()
    config_module.settings = new_settings
    for name in modules_with_settings:
        setattr(sys.modules[name], "settings", new_settings)
