"""SQLAlchemy engine and session configuration."""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
if settings.database_password is not None and not settings.database_url.startswith("sqlite"):
    connect_args["password"] = settings.database_password.get_secret_value()

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    future=True,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_timeout=10,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base for ORM models."""

    pass


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
