"""Test configuration and fixtures."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import Depends, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="pi-analytics-tests-"))
TEST_DB_PATH = TEST_DB_DIR / "database.sqlite3"
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_PATH}"

# Test execution must never inherit a real database URL from the shell or a
# developer .env.  This assignment is intentional (not setdefault): every
# pytest process receives an isolated SQLite database created for this run.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_DEBUG"] = "false"
os.environ["PI_WEB_API_BASE_URL"] = ""
os.environ["PI_DATA_SERVER_NAME"] = ""
os.environ["AUTH_JWT_SECRET"] = "test-only-secret-that-is-at-least-thirty-two-characters"

if not TEST_DATABASE_URL.startswith("sqlite:///") or Path(TEST_DB_PATH).parent != TEST_DB_DIR:
    raise RuntimeError("Refusing to run tests: database is not the isolated SQLite test database.")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.api import deps  # noqa: E402
from app.api.deps import get_db_session, get_norm_limits_service, get_pi_provider, get_pi_service  # noqa: E402
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
from app.api.deps import get_authenticated_user, get_current_user, validate_csrf  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services.pi_norm_limits_service import PiNormLimitsService  # noqa: E402
from app.services.pi_service import PiService  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from tests.pi_fakes import FakePiDataProvider  # noqa: E402

_ADMIN_TEST_HASH = hash_password("admin")

engine = create_engine(
    os.environ["DATABASE_URL"],
    connect_args={"check_same_thread": False},
    # A file-backed test database must use one connection per session/thread;
    # StaticPool shares a sqlite handle across concurrent TestClient requests.
    poolclass=NullPool,
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
    engine.dispose()
    shutil.rmtree(TEST_DB_DIR)


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

    # Only HTTP-client tests need the conventional authenticated principal.
    # Keeping it out of the autouse fixture leaves first-admin tests with an
    # actually empty user table and makes test ordering irrelevant.
    with TestingSessionLocal() as db:
        if db.query(User).filter(User.normalized_username == "test-admin").first() is None:
            db.add(User(
                username="test-admin",
                normalized_username="test-admin",
                password_hash=_ADMIN_TEST_HASH,
                role=UserRole.ADMIN,
                is_active=True,
                auth_version=1,
                must_change_password=False,
            ))
            db.commit()

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

    def _norm_limits_override(
        db=Depends(_db_override),
        provider=Depends(_provider_override),
    ):
        return PiNormLimitsService(db, provider=provider)

    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_db_session] = _db_override
    app.dependency_overrides[get_pi_provider] = _provider_override
    app.dependency_overrides[get_pi_service] = _service_override
    app.dependency_overrides[get_norm_limits_service] = _norm_limits_override

    def _authenticated_user(request: Request):
        # Keep the convenient implicit test-admin for legacy endpoint tests,
        # but honor a real session cookie when a test explicitly logs in as a
        # different user.  Removing this override still exercises the real
        # authentication dependency and returns 401 without a cookie.
        if request.cookies.get(settings.auth_cookie_name):
            return get_authenticated_user(request)
        db = TestingSessionLocal()
        try:
            user = db.query(User).filter(User.normalized_username == "test-admin").first()
            if not user:
                user = User(username="test-admin", normalized_username="test-admin", password_hash=_ADMIN_TEST_HASH, role=UserRole.ADMIN, is_active=True, auth_version=1, must_change_password=False)
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
