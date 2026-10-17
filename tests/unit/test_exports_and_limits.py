import csv
import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.rate_limits import FixedWindowRateLimiter
from app.db.models import FinancialFact
from app.services.exports import EXPORT_COLUMNS, export_filename, render_csv, render_json


def _fact(**overrides):
    now = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    base = dict(
        cik="0000000001",
        metric="revenue",
        value=Decimal("-1234.5"),
        unit="USD",
        currency="USD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        period_type="duration",
        period_class="annual",
        fiscal_year=2024,
        fiscal_period="FY",
        form_type="10-K",
        filed_date=date(2025, 2, 1),
        accession_number="0000000001-25-000001",
        source_tag="Revenues",
        source_taxonomy="us-gaap",
        source_url="https://www.sec.gov/x",
        mapping_version="1.0.0",
        quality_status="ok",
        derived=False,
        observation_key="k",
        first_detected_at=now,
        processed_at=now,
    )
    base.update(overrides)
    return FinancialFact(**base)


def test_csv_escaping_and_nulls():
    f = _fact(
        source_tag='Tag "quoted", with, commas\nand newline ✓',
        value=None,
        currency=None,
        fiscal_year=None,
    )
    data = render_csv([f]).decode("utf-8")
    rows = list(csv.reader(io.StringIO(data)))
    assert rows[0] == EXPORT_COLUMNS
    row = dict(zip(EXPORT_COLUMNS, rows[1], strict=True))
    assert row["source_tag"] == 'Tag "quoted", with, commas\nand newline ✓'
    assert row["value"] == "" and row["currency"] == "" and row["fiscal_year"] == ""
    assert row["first_detected_at"] == "2026-10-17T12:00:00Z" and row["derived"] == "false"


def test_csv_preserves_sign_and_decimal_without_exponent():
    row = list(
        csv.reader(io.StringIO(render_csv([_fact(value=Decimal("391035000000"))]).decode()))
    )[1]
    assert row[EXPORT_COLUMNS.index("value")] == "391035000000"
    row = list(csv.reader(io.StringIO(render_csv([_fact()]).decode())))[1]
    assert row[EXPORT_COLUMNS.index("value")] == "-1234.5"


def test_json_export_shape():
    body = json.loads(render_json([_fact(value=Decimal("5"))], {"rows_returned": 1}))
    assert body["meta"]["rows_returned"] == 1
    rec = body["data"][0]
    assert (
        rec["value"] == 5
        and rec["period_end"] == "2024-12-31"
        and rec["processed_at"].endswith("Z")
    )
    assert set(rec) == set(EXPORT_COLUMNS)


def test_export_filename_is_safe():
    name = export_filename("revenue; rm -rf /", ["1", "2"], "csv", datetime(2026, 1, 1, tzinfo=UTC))
    assert name == "facts_revenuerm-rf_ciks2_20260101T000000Z.csv"


def test_rate_limiter_window():
    rl = FixedWindowRateLimiter(window_seconds=60)
    t0 = 1_000_000.0
    for _ in range(3):
        assert rl.check("k", 3, now=t0).allowed
    d = rl.check("k", 3, now=t0 + 1)
    assert not d.allowed and d.retry_after_seconds >= 1
    assert rl.check("other", 3, now=t0 + 1).allowed
    assert rl.check("k", 3, now=t0 + 61).allowed
