"""Refuse to run code against a database whose schema is behind it (or ahead of it).

Every job entry point (scripts/_bootstrap.py: the poller, the tracker, build_marts, the loaders)
and the API's /readyz compare the database's alembic revision with the code's migration head.
A job then stops once with "schema behind code: run alembic upgrade head" instead of failing
once per company (2026-11-22: 1,061 mart refreshes failed on a table not yet created).

A database without an alembic_version table (tables made by the test suite or create_all) is not
checked.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]


class SchemaMismatch(RuntimeError):
    pass


def _scripts():
    """The migrations folder (no alembic.ini needed: only the revisions are read)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "app" / "db" / "migrations"))
    return ScriptDirectory.from_config(cfg)


@lru_cache(maxsize=1)
def code_head() -> str:
    heads = _scripts().get_heads()
    if len(heads) != 1:
        raise SchemaMismatch(f"the migrations have {len(heads)} heads; merge them first")
    return heads[0]


def db_revision(engine: Engine) -> str | None:
    """The database's alembic revision, or None when it has no alembic_version table."""
    if not inspect(engine).has_table("alembic_version"):
        return None
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def problem(engine: Engine) -> str | None:
    """None when the schema matches the code; otherwise what is wrong and what to run."""
    rev = db_revision(engine)
    if rev is None:
        return None
    head = code_head()
    if rev == head:
        return None
    known = {s.revision for s in _scripts().walk_revisions()}
    if rev not in known:
        return (f"schema ahead of code: the database is at {rev}, which this code does not "
                f"know (code head {head}); deploy the newer code")  # fmt: skip
    return (f"schema behind code: the database is at {rev}, the code needs {head}; "
            "run alembic upgrade head")  # fmt: skip


def require_current(engine: Engine) -> None:
    msg = problem(engine)
    if msg:
        raise SchemaMismatch(msg)
