"""M-01: one filing reporting two figures for a period, IFRS beside US GAAP (a parent-only
schedule's tag). The figure the company's other filings back is shown; when none is backed, the
cell is blank with a note. Ties between equal filings are settled the same way every run."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from app.db.models import Company, FinancialFact
from app.services import filing_conflicts

CIK = "0000000920"
A, B = "0000000920-20-000001", "0000000920-21-000001"


def _fact(metric, value, end, acc, filed, tax="ifrs-full", tag="Liabilities", cik=CIK, key=None):
    now = datetime.now(UTC)
    instant = metric == "total_liabilities"
    return FinancialFact(
        cik=cik, metric=metric, value=value, unit="CLP", currency="CLP",
        period_start=None if instant else date(end.year, 1, 1), period_end=end,
        period_type="instant" if instant else "duration", period_class="annual",
        fiscal_year=end.year, fiscal_period="FY", form_type="20-F", filed_date=filed,
        accession_number=acc, source_tag=tag, source_taxonomy=tax,
        source_url=f"https://www.sec.gov/Archives/{acc}", mapping_version="1.5.0",
        quality_status="ok", derived=False, first_detected_at=now, processed_at=now,
        observation_key=key or hashlib.sha256(f"{cik}{metric}{acc}{tax}{end}".encode()).hexdigest(),
    )  # fmt: skip


def _company(db, cik=CIK):
    now = datetime.now(UTC)
    db.add(Company(cik=cik, legal_name="BANCO EJEMPLO", fiscal_year_end="1231",
                   fiscal_year_ends="2019-12-31,2020-12-31", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now,
                   quality_status="ok"))  # fmt: skip


def _seed(db):
    _company(db)
    y19, y20 = date(2019, 12, 31), date(2020, 12, 31)
    f20, f21 = date(2020, 4, 30), date(2021, 4, 30)
    db.add_all([
        # Santander Chile-like: consolidated 47.1 and parent-only 8.39 in one 20-F; the next
        # 20-F's comparative backs 47.1
        _fact("total_liabilities", 47_100, y19, A, f20),
        _fact("total_liabilities", 8_390, y19, A, f20, "us-gaap"),
        _fact("total_liabilities", 47_100, y19, B, f21),
        _fact("total_liabilities", 50_000, y20, B, f21),
        # revenue 2019: two figures in one filing, no other filing backs either
        _fact("revenue", 1_000, y19, A, f20, tag="Revenue"),
        _fact("revenue", 600, y19, A, f20, "us-gaap", "Revenues"),
        _fact("revenue", 1_100, y20, B, f21, tag="Revenue"),
    ])  # fmt: skip
    db.commit()


def test_the_backed_figure_stays_and_the_unbacked_cell_is_blank(client, auth, db):
    _seed(db)
    found = filing_conflicts.find(db, [CIK])
    picked = sorted((c["metric"], c["keep"]) for c in found)
    assert picked == [("revenue", None), ("total_liabilities", 47_100)]
    assert filing_conflicts.apply(db, [CIK]) == 3  # 8.39, and both 2019 revenues
    db.commit()
    assert filing_conflicts.apply(db, [CIK]) == 0  # a second run changes nothing
    bal = client.get(f"/v1/companies/{CIK}/statements/balance?period=annual",
                     headers=auth).json()  # fmt: skip
    (liab,) = [r for r in bal["rows"] if r["metric"] == "total_liabilities"]
    assert liab["cells"][0]["value"] == 47_100 and liab["cells"][0]["quality_note"] is None
    inc = client.get(f"/v1/companies/{CIK}/statements/income?period=annual",
                     headers=auth).json()  # fmt: skip
    (rev,) = [r for r in inc["rows"] if r["metric"] == "revenue"]
    first, second = rev["cells"]
    assert first["value"] is None and first["quality_note"] == filing_conflicts.NOTE
    assert second["value"] == 1_100 and second["quality_note"] is None


def test_a_tie_between_equal_filings_is_settled_the_same_way_every_run(client, auth, db):
    """Two figures for one period, same filing and filed date: the pick never depends on the
    order the rows were stored in."""
    y = date(2019, 12, 31)
    for cik, order in (("0000000921", (0, 1)), ("0000000922", (1, 0))):
        _company(db, cik)
        rows = [_fact("revenue", 700, y, f"{cik}-20-000001", date(2020, 4, 30), tag="Revenue",
                      cik=cik, key="a" * 64),
                _fact("revenue", 900, y, f"{cik}-20-000001", date(2020, 4, 30), tag="Revenue",
                      cik=cik, key="b" * 64)]  # fmt: skip
        for i in order:
            db.add(rows[i])
            db.commit()
    picks = set()
    for cik in ("0000000921", "0000000922"):
        body = client.get(f"/v1/companies/{cik}/statements/income?period=annual",
                          headers=auth).json()  # fmt: skip
        (rev,) = [r for r in body["rows"] if r["metric"] == "revenue"]
        picks.add(rev["cells"][0]["value"])
    assert picks == {900}
