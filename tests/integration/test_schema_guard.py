"""Jobs and /readyz refuse to run against a database whose schema is behind the code."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.db import schema_guard

ROOT = Path(__file__).resolve().parents[2]


def _engine(tmp_path, rev):
    eng = create_engine(f"sqlite:///{tmp_path / 'g.sqlite3'}")
    if rev is not None:
        with eng.begin() as c:
            c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            c.execute(text("INSERT INTO alembic_version VALUES (:r)"), {"r": rev})
    return eng


def test_current_behind_ahead_and_untracked(tmp_path):
    head = schema_guard.code_head()
    (tmp_path / "a").mkdir()
    assert schema_guard.problem(_engine(tmp_path / "a", head)) is None
    (tmp_path / "b").mkdir()
    old = _engine(tmp_path / "b", "a9d3f1b7c5e2")
    behind = schema_guard.problem(old)
    assert behind.startswith("schema behind code") and "alembic upgrade head" in behind
    (tmp_path / "c").mkdir()
    ahead = schema_guard.problem(_engine(tmp_path / "c", "ffffffffffff"))
    assert ahead.startswith("schema ahead of code")
    (tmp_path / "d").mkdir()
    assert schema_guard.problem(_engine(tmp_path / "d", None)) is None  # no alembic table
    with pytest.raises(schema_guard.SchemaMismatch):
        schema_guard.require_current(old)


def test_a_job_refuses_to_start_once_with_a_clear_message(tmp_path):
    _engine(tmp_path, "a9d3f1b7c5e2")
    env = {"DATABASE_URL": f"sqlite:///{tmp_path / 'g.sqlite3'}", "PATH": "/usr/bin:/bin",
           "SEC_USER_AGENT": "Provenance-tests/0.1 contact=tests@provenance.test"}  # fmt: skip
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_mapping.py")], env=env,
                       capture_output=True, text=True, cwd=ROOT, timeout=120)  # fmt: skip
    assert r.returncode == 2, r.stderr
    assert "refusing to start: schema behind code" in r.stderr
    assert "run alembic upgrade head" in r.stderr


def test_readyz_reports_a_schema_behind_the_code(client, engine):
    with engine.begin() as c:
        c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        c.execute(text("INSERT INTO alembic_version VALUES ('a9d3f1b7c5e2')"))
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json()["schema"].startswith("schema behind code")
    with engine.begin() as c:
        c.execute(text("UPDATE alembic_version SET version_num = :h"),
                  {"h": schema_guard.code_head()})  # fmt: skip
    assert client.get("/readyz").json()["schema"] == "ok"
