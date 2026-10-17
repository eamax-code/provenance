"""Bounded CSV/JSON export of normalized facts with full provenance columns."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal

from app.db.models import FinancialFact

EXPORT_COLUMNS = [
    "cik",
    "metric",
    "value",
    "unit",
    "currency",
    "period_start",
    "period_end",
    "period_type",
    "period_class",
    "fiscal_year",
    "fiscal_period",
    "form_type",
    "filed_date",
    "accession_number",
    "source_tag",
    "source_url",
    "mapping_version",
    "quality_status",
    "derived",
    "first_detected_at",
    "processed_at",
]


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _json_cell(value):
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Decimal):
        f = float(value)
        return int(f) if f.is_integer() and abs(f) < 2**53 else f
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def fact_row(f: FinancialFact) -> dict:
    return {col: getattr(f, col) for col in EXPORT_COLUMNS}


def render_csv(facts: list[FinancialFact]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for f in facts:
        row = fact_row(f)
        writer.writerow([_cell(row[c]) for c in EXPORT_COLUMNS])
    return buf.getvalue().encode("utf-8")


def render_json(facts: list[FinancialFact], meta: dict) -> bytes:
    rows = [{c: _json_cell(v) for c, v in fact_row(f).items()} for f in facts]
    return json.dumps({"data": rows, "meta": meta}, separators=(",", ":")).encode("utf-8")


_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def export_filename(metric: str | None, ciks: list[str], fmt: str, now: datetime) -> str:
    parts = ["facts"]
    if metric:
        parts.append(_SAFE.sub("", metric)[:32])
    if ciks:
        parts.append("ciks" + str(len(ciks)))
    parts.append(now.strftime("%Y%m%dT%H%M%SZ"))
    ext = "csv" if fmt == "csv" else "json"
    return "_".join(parts) + "." + ext
