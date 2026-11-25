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
    assert tr["period_fiscal_year"] is None and tr["transition_form"] == "10-KT"


def test_a_reverse_acquisition_keeps_both_years_without_duplicate_keys(client, auth, db):
    """Eros: March years in its own 20-Fs; after the merger a 20-F transition report presents
    the accounting acquirer's (STX's) years ended September 2017-2019 and the six months to
    March 2020. Every reported year is a column, month-suffixed where two share a label."""
    now = datetime.now(UTC)
    eros = "0000000906"
    db.add(Company(cik=eros, legal_name="EROS PLC", ticker="EROS", fiscal_year_end="0331",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    f19, f20, ft = date(2019, 8, 1), date(2020, 7, 30), date(2020, 10, 30)
    a19, a20, tr = "0000000906-19-000001", "0000000906-20-000001", "0000000906-20-000009"
    rows = [
        ("revenue", 200, date(2017, 4, 1), date(2018, 3, 31), "annual", a19, "20-F", f19),
        ("revenue", 210, date(2018, 4, 1), date(2019, 3, 31), "annual", a19, "20-F", f19),
        ("revenue", 220, date(2019, 4, 1), date(2020, 3, 31), "annual", a20, "20-F", f20),
        ("revenue", 400, date(2016, 10, 1), date(2017, 9, 30), "annual", tr, "20-F", ft),
        ("revenue", 410, date(2017, 10, 1), date(2018, 9, 30), "annual", tr, "20-F", ft),
        ("revenue", 420, date(2018, 10, 1), date(2019, 9, 30), "annual", tr, "20-F", ft),
        ("revenue", 190, date(2019, 10, 1), date(2020, 3, 31), "ytd", tr, "20-F", ft),
    ]
    for r in rows:
        f = _fact(*r)
        f.cik = eros
        db.add(f)
    db.commit()
    from app.services import fiscal_years

    assert fiscal_years.own_year_ends(db, [eros])[eros] == [
        date(2017, 9, 30), date(2018, 3, 31), date(2018, 9, 30), date(2019, 3, 31),
        date(2019, 9, 30), date(2020, 3, 31)]  # fmt: skip
    body = client.get(f"/v1/companies/{eros}/statements/income?period=annual",
                      headers=auth).json()  # fmt: skip
    keys = [c["key"] for c in body["columns"]]
    assert keys == ["FY2017", "FY2018 (Mar)", "FY2018 (Sep)", "FY2019 (Mar)", "FY2019 (Sep)",
                    "FY2020"]  # fmt: skip
    assert len(set(keys)) == len(keys)


def test_an_interim_in_a_10k_or_a_first_period_is_not_a_transition(db):
    now = datetime.now(UTC)
    for cik, name in (("0000000907", "SAFESPACE"), ("0000000908", "NEWCO SPAC")):
        db.add(Company(cik=cik, legal_name=name, source_url="https://www.sec.gov/",
                       first_detected_at=now, last_processed_at=now,
                       quality_status="ok"))  # fmt: skip
    rows = [
        # SafeSpace: July years; its July 2019 10-K also carries six months to January 2020
        ("0000000907", 100, date(2017, 8, 1), date(2018, 7, 31), "annual", "s-18", "10-K"),
        ("0000000907", 110, date(2018, 8, 1), date(2019, 7, 31), "annual", "s-19", "10-K"),
        ("0000000907", 60, date(2019, 8, 1), date(2020, 1, 31), "ytd", "s-19", "10-K"),
        ("0000000907", 120, date(2019, 8, 1), date(2020, 7, 31), "annual", "s-20", "10-K"),
        # a SPAC's first 10-K: from inception in March to December
        ("0000000908", -5, date(2021, 3, 1), date(2021, 12, 31), "other", "n-21", "10-K"),
        ("0000000908", -9, date(2022, 1, 1), date(2022, 12, 31), "annual", "n-22", "10-K"),
    ]
    for cik, v, start, end, cls, acc, form in rows:
        f = _fact("revenue", v, start, end, cls, acc, form, end)
        f.cik = cik
        db.add(f)
    db.commit()
    from app.services import fiscal_years

    assert fiscal_years.transitions(db, ["0000000907", "0000000908"]) == {}
