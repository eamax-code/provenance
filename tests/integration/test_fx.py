"""H.10 rates for USD-equivalent size cohorts: parsing both rate directions, the annual
average, and None for short periods, sparse rates or uncovered currencies."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.services import fx

CSV = """"Series Description","Euro-Area Euro","Japanese Yen"
"Unit:","Currency","Currency"
"Multiplier:","1","1"
"Currency:","EUR","JPY"
"Unique Identifier: ","H10/H10/RXI$US_N.B.EU","H10/H10/RXI_N.B.JA"
"Time Period","RXI$US_N.B.EU","RXI_N.B.JA"
{rows}
"""


def _csv(days=260, eur="1.1000", jpy="150.00"):
    start = date(2025, 1, 1)
    lines = [f"{start + timedelta(days=i)},{eur},{jpy}" for i in range(days)]
    lines.append(f"{start + timedelta(days=days)},ND,ND")
    return CSV.format(rows="\n".join(lines))


def test_parse_keeps_each_series_direction_and_skips_nd():
    rows = fx.parse_h10(_csv(days=2))
    eur = [r for r in rows if r["currency"] == "EUR"]
    assert len(eur) == 2 and eur[0]["usd_per_unit"] and eur[0]["value"] == Decimal("1.1000")
    assert not [r for r in rows if r["currency"] == "JPY"][0]["usd_per_unit"]


def test_usd_equivalent_annual_only_and_covered_currencies_only(db):
    fx.load(db, _csv())
    year = (date(2025, 1, 1), date(2025, 12, 31))
    # SAP-style check: EUR 36.8B at 1.10 USD per euro
    assert fx.usd_equivalent(db, Decimal("36.8e9"), "EUR", *year) == Decimal("36.8e9") * Decimal(
        "1.1"
    )
    assert fx.usd_equivalent(db, Decimal("1.5e11"), "JPY", *year) == Decimal("1e9")
    assert fx.usd_equivalent(db, 5, "USD", *year) == 5
    assert fx.usd_equivalent(db, 5, "ARS", *year) is None  # not covered by H.10
    assert fx.usd_equivalent(db, 5, "EUR", date(2025, 1, 1), date(2025, 3, 31)) is None  # quarter
    fx.load(db, _csv(days=100))
    assert fx.usd_equivalent(db, 5, "EUR", *year) is None  # under 200 rate days
