"""Bounded CSV/JSON export of normalized facts with full provenance columns."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal

from app.db.models import FinancialFact, MartCompanyPeriod
from app.services import periods
from app.services.quality import is_suspicious_period

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
    "period_fiscal_year",  # the fiscal year the period belongs to
    "period_label",  # "FY2025", "Q1 FY2026"
    "calendar_period",  # "CY2025Q3", as the SEC frames it
    "filing_fiscal_year",  # the SEC fy label of the filing that reported it (not the period's)
    "filing_fiscal_period",
    "form_type",
    "filed_date",
    "accession_number",
    "source_tag",
    "source_url",
    "mapping_version",
    "quality_status",
    "derived",
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


_RENAMED = {"filing_fiscal_year": "fiscal_year", "filing_fiscal_period": "fiscal_period"}
_COMPUTED = ("period_fiscal_year", "period_label", "calendar_period")


def fact_row(f: FinancialFact, fiscal_year_end: str | None = None) -> dict:
    row = {col: getattr(f, _RENAMED.get(col, col)) for col in EXPORT_COLUMNS
           if col not in _COMPUTED}  # fmt: skip
    row["period_fiscal_year"] = periods.fiscal_year(f.period_end, fiscal_year_end)
    row["period_label"] = (
        periods.label(f.period_end, f.period_class, fiscal_year_end)
        if f.period_class in ("annual", "quarterly") else None
    )  # fmt: skip
    row["calendar_period"] = periods.calendar_period(f.period_start, f.period_end, f.period_class)
    if is_suspicious_period(f.period_end, f.filed_date):
        row["quality_status"] = "suspicious_period"
    return {col: row[col] for col in EXPORT_COLUMNS}


def render_csv(facts: list[FinancialFact], year_ends: dict[str, str | None] | None = None) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(EXPORT_COLUMNS)
    for f in facts:
        row = fact_row(f, (year_ends or {}).get(f.cik))
        writer.writerow([_cell(row[c]) for c in EXPORT_COLUMNS])
    return buf.getvalue().encode("utf-8")


def render_json(
    facts: list[FinancialFact], meta: dict, year_ends: dict[str, str | None] | None = None
) -> bytes:
    rows = [{c: _json_cell(v) for c, v in fact_row(f, (year_ends or {}).get(f.cik)).items()}
            for f in facts]  # fmt: skip
    return json.dumps({"data": rows, "meta": meta}, separators=(",", ":")).encode("utf-8")


PERIOD_METRICS = [
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "operating_cash_flow",
]
PERIOD_COLUMNS = (
    ["cik", "company", "period_fiscal_year", "period_label", "period_end", "unit"]
    + PERIOD_METRICS
    + [f"{m}_filing_url" for m in PERIOD_METRICS]
)


def period_row(row: MartCompanyPeriod, company: str | None) -> dict:
    """One company-year of mart_company_period, with each figure's filing link."""
    sources = json.loads(row.sources) if row.sources else {}
    out = {
        "cik": row.cik,
        "company": company,
        "period_fiscal_year": row.fiscal_year,  # the mart's year is the period's own
        "period_label": f"FY{row.fiscal_year}",
        "period_end": row.period_end,
        "unit": row.currency or "USD",  # D-04: the company's reporting currency
    }
    out |= {m: getattr(row, m) for m in PERIOD_METRICS}
    return out | {f"{m}_filing_url": sources.get(m) for m in PERIOD_METRICS}


def render_rows_csv(rows: list[dict], columns: list[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row[c]) for c in columns])
    return buf.getvalue().encode("utf-8")


def render_rows_json(rows: list[dict], meta: dict) -> bytes:
    data = [{c: _json_cell(v) for c, v in row.items()} for row in rows]
    return json.dumps({"data": data, "meta": meta}, separators=(",", ":")).encode("utf-8")


_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def export_filename(
    metric: str | None, ciks: list[str], fmt: str, now: datetime, kind: str = "facts"
) -> str:
    parts = [kind]
    if metric:
        parts.append(_SAFE.sub("", metric)[:32])
    if ciks:
        parts.append("ciks" + str(len(ciks)))
    parts.append(now.strftime("%Y%m%dT%H%M%SZ"))
    ext = "csv" if fmt == "csv" else "json"
    return "_".join(parts) + "." + ext
