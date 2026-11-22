from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
# rate limits and usage metering (R-2, 2026-11-22 evening): a request held its pooled connection
# while waiting for a second one for these, so under load every connection was held and requests
# timed out after 30 s. They get a small pool of their own that request handlers never touch, and
# fail fast (rate limits then fall back to per-process counters; metering logs and moves on).
CONTROL_POOL = {"pool_size": 3, "max_overflow": 2, "pool_timeout": 2}
_control: Engine | None = None
_ControlSession: sessionmaker[Session] | None = None


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
    _dispose_control()
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(database_url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def set_engine(engine: Engine) -> None:
    global _engine, _SessionLocal
    _dispose_control()
    if _engine is not None and _engine is not engine:
        _engine.dispose()
    _engine = engine
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)


def _dispose_control() -> None:
    global _control, _ControlSession
    if _control is not None and _control is not _engine:
        _control.dispose()
    _control = _ControlSession = None


def control_engine() -> Engine:
    """The engine for rate limits and usage metering: its own small pool on the same database. An
    in-memory SQLite database (one shared connection) keeps the main engine, since a second
    engine would open another, empty database."""
    global _control, _ControlSession
    main = get_engine()
    if isinstance(main.pool, StaticPool):
        return main
    if _control is None or _control.url != main.url:
        _dispose_control()
        if main.dialect.name == "sqlite":
            kwargs: dict = {"connect_args": {"check_same_thread": False}}
        else:
            kwargs = {"pool_pre_ping": True}
        _control = create_engine(main.url, **kwargs, **CONTROL_POOL)
    return _control


def control_session_factory() -> sessionmaker[Session]:
    global _ControlSession
    engine = control_engine()
    if _ControlSession is None or _ControlSession.kw.get("bind") is not engine:
        _ControlSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return _ControlSession


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
