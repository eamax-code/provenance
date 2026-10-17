"""Shared CLI bootstrap: logging, settings, DB session."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.session import configure_engine, session_factory  # noqa: E402


def bootstrap():
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    configure_engine(settings.database_url)
    return settings, session_factory()
