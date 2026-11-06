from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def make_engine(database_url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if database_url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}, "future": True}
        if ":memory:" in database_url or database_url.endswith("sqlite://"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def configure_engine(database_url: str) -> Engine:
    """The engine for this URL: the current one if it already points there, else a new one (the
    one it replaces is disposed, so its pooled connections are closed, not left to the GC)."""
    global _engine, _SessionLocal
    if _engine is not None and _engine.url.render_as_string(hide_password=False) == database_url:
        return _engine
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(database_url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def set_engine(engine: Engine) -> None:
    global _engine, _SessionLocal
    if _engine is not None and _engine is not engine:
        _engine.dispose()
    _engine = engine
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)


def get_engine() -> Engine:
    if _engine is None:
        from app.core.config import get_settings

        configure_engine(get_settings().database_url)
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
