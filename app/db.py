from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _sqlite_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Not a file sqlite URL")
    raw_path = database_url[len(prefix) :]
    return Path(raw_path)


def build_engine(database_url: str, echo: bool = False) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if database_url.startswith("sqlite:///"):
            db_path = _sqlite_path(database_url)
            if db_path.parent != Path("."):
                db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(database_url, echo=echo, future=True, connect_args=connect_args)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


settings = get_settings()
engine = build_engine(settings.database_url, echo=settings.echo_sql)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db(target_engine: Engine = engine) -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=target_engine)
