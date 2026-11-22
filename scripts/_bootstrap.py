"""Shared CLI bootstrap: logging, settings, DB session."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.schema_guard import SchemaMismatch, require_current  # noqa: E402
from app.db.session import configure_engine, get_engine, session_factory  # noqa: E402


def bootstrap(check_schema: bool = True):
    """Settings and a session factory. Refuses to start (exit 2) when the database schema does
    not match the code's migrations, so a job never fails once per company on a missing table."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    configure_engine(settings.database_url)
    if check_schema:
        try:
            require_current(get_engine())
        except SchemaMismatch as exc:
            print(f"refusing to start: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    return settings, session_factory()
