"""USD equivalents for size cohorts, from the Federal Reserve's H.10 daily rates (public domain).

Used only to place companies that report in different currencies in the same size cohort (the
$1B+ lists in the quality report and coverage); never shown as a company's figure, which stays
in its reporting currency. An amount converts at the average of the daily rates over its fiscal
year; a period shorter than about 300 days, fewer than 200 rate days, or a currency H.10 does
not cover (ARS, CLP, COP, PEN, IDR, ILS, TRY...) gives None. The file's address and the load
time are kept out of every response; cohort notes name "Federal Reserve H.10" in words only.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db.models import FxRate

# every H.10 currency in one series package, as CSV; the endpoint returns nothing for an open
# range, so the dates are given
H10_FROM = date(2010, 1, 1)


def h10_url(to: date) -> str:
    return ("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H10"
            "&series=60f32914ab61dfab590e0e470153e3ae&lastobs="
            f"&from={H10_FROM:%m/%d/%Y}&to={to:%m/%d/%Y}&filetype=csv&label=include"
            "&layout=seriescolumn")  # fmt: skip


SOURCE_NAME = "Federal Reserve H.10"
MIN_PERIOD_DAYS = 300
MIN_RATE_DAYS = 200


def parse_h10(text: str) -> list[dict]:
    """Rows {currency, rate_date, value, usd_per_unit, series_id}; 'ND' days are skipped."""
    rows = list(csv.reader(io.StringIO(text)))
    head = {r[0].strip().rstrip(":").strip(): r[1:] for r in rows if r and not r[0][:2].isdigit()}
    currencies = [c.strip() for c in head.get("Currency", [])]
    series = [s.strip() for s in head.get("Time Period", [])]
    out = []
    for r in rows:
        if not r or not r[0][:4].isdigit():
            continue
        day = date.fromisoformat(r[0].strip())
        for cur, sid, raw in zip(currencies, series, r[1:], strict=False):
            try:
                v = Decimal(raw.strip())
            except InvalidOperation:
                continue  # ND: no rate that day
            if v <= 0 or len(cur) != 3:
                continue
            out.append({"currency": cur, "rate_date": day, "value": v,
                        "usd_per_unit": "$US" in sid, "series_id": sid})  # fmt: skip
    return out


def load(db: Session, text: str) -> int:
    rows = parse_h10(text)
    db.execute(delete(FxRate))
    for i in range(0, len(rows), 5000):
        db.execute(insert(FxRate), rows[i : i + 5000])
    db.commit()
    return len(rows)


def usd_equivalent(
    db: Session, amount, currency: str | None, start: date | None, end: date | None
) -> Decimal | None:
    """The amount in US dollars at the average H.10 rate over [start, end]; None when the period
    is shorter than an annual one, rates are missing for it, or the currency is not covered."""
    if amount is None or not currency or start is None or end is None:
        return None
    amount = Decimal(str(amount))
    if currency.upper() == "USD":
        return amount
    if (end - start).days < MIN_PERIOD_DAYS:
        return None
    vals = db.execute(
        select(FxRate.value, FxRate.usd_per_unit).where(
            FxRate.currency == currency.upper(), FxRate.rate_date.between(start, end)
        )
    ).all()
    n = len(vals)
    avg = sum((v for v, _ in vals), Decimal(0)) / n if n else None
    per = vals[0][1] if vals else None
    if not n or n < MIN_RATE_DAYS or avg is None:
        return None
    avg = Decimal(str(avg))
    return amount * avg if per else amount / avg
