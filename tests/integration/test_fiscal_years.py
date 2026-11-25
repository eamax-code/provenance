"""S-07: annual statement columns are the company's own fiscal years, each named by its own end
date; a year-end changer's transition period (10-KT) is its own column, never a fiscal year."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from app.db.models import Company, FinancialFact

CIK = "0000000905"


def _key(*parts) -> str:
    return hashlib.sha256("".join(map(str, parts)).encode()).hexdigest()


def _fact(metric, value, start, end, cls, acc, form, filed):
    now = datetime.now(UTC)
    return FinancialFact(
        cik=CIK, metric=metric, value=value, unit="USD", currency="USD", period_start=start,
        period_end=end, period_type="duration", period_class=cls, fiscal_year=end.year,
        fiscal_period="FY", form_type=form, filed_date=filed, accession_number=acc,
        source_tag="Revenues" if metric == "revenue" else "NetIncomeLoss",
        source_taxonomy="us-gaap", source_url=f"https://www.sec.gov/Archives/{acc}",
        mapping_version="1.5.0", quality_status="ok", derived=False, first_detected_at=now,
        processed_at=now, observation_key=_key(metric, acc, start, end))  # fmt: skip


def _seed(db):
    now = datetime.now(UTC)
    # December years until 2020, then a 9-month transition to September 2021 (a 10-KT); the
    # stored year end is today's (September), which used to name December 2020 "FY2021"
    db.add(Company(cik=CIK, legal_name="CHANGER INC", ticker="CHNG", fiscal_year_end="0930",
                   fiscal_year_ends="2019-12-31,2020-12-31,2022-09-30",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    a, b, t, c = ("0000000905-20-000001", "0000000905-21-000001", "0000000905-21-000009",
                  "0000000905-22-000001")  # fmt: skip
    db.add_all([
        _fact("revenue", 100, date(2019, 1, 1), date(2019, 12, 31), "annual", a, "10-K",
              date(2020, 3, 1)),
        _fact("revenue", 110, date(2020, 1, 1), date(2020, 12, 31), "annual", b, "10-K",
              date(2021, 3, 1)),
        # a 12-month period to June 2020 in the same 10-K (pro forma): not a fiscal year
        _fact("revenue", 105, date(2019, 7, 1), date(2020, 6, 30), "annual", b, "10-K",
              date(2021, 3, 1)),
        _fact("revenue", 90, date(2021, 1, 1), date(2021, 9, 30), "other", t, "10-KT",
              date(2021, 12, 1)),
        _fact("revenue", 130, date(2021, 10, 1), date(2022, 9, 30), "annual", c, "10-K",
              date(2022, 12, 1)),
    ])  # fmt: skip
    db.commit()


def test_columns_are_own_years_by_their_own_end_plus_the_transition(client, auth, db):
    _seed(db)
    body = client.get(f"/v1/companies/{CIK}/statements/income?period=annual",
                      headers=auth).json()  # fmt: skip
    cols = [(c["key"], c["period_end"], c["transition"]) for c in body["columns"]]
    assert cols == [("FY2019", "2019-12-31", False), ("FY2020", "2020-12-31", False),
                    ("Transition period (9 months, ended 2021-09-30)", "2021-09-30", True),
                    ("FY2022", "2022-09-30", False)]  # fmt: skip
    assert len({c[0] for c in cols}) == len(cols)  # no duplicate keys
    (rev,) = [r for r in body["rows"] if r["metric"] == "revenue"]
    values = {c["column"]: c["value"] for c in rev["cells"] if c}
    assert values["Transition period (9 months, ended 2021-09-30)"] == 90
    assert 105 not in values.values()  # the June 12-month period is not a column
    tr = next(c for c in body["columns"] if c["transition"])
    assert tr["period_fiscal_year"] is None
