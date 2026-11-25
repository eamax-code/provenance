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


def test_quarters_inside_a_transition_are_labelled_by_it(client, auth, db):
    """Precision Castparts: the quarters of a 9-month transition are never Q2-Q4 of the fiscal
    year before it (which has its own Q2-Q4): unique keys, transition: true."""
    _seed(db)  # December years, then a 10-KT from January to September 2021
    t = "0000000905-21-000009"
    for q, (s, e) in enumerate([(date(2021, 1, 1), date(2021, 3, 31)),
                                (date(2021, 4, 1), date(2021, 6, 30)),
                                (date(2021, 7, 1), date(2021, 9, 30))], 1):  # fmt: skip
        db.add(_fact("revenue", 30 + q, s, e, "quarterly", t, "10-KT", date(2021, 12, 1)))
    for q, (s, e) in enumerate([(date(2020, 4, 1), date(2020, 6, 30)),
                                (date(2020, 7, 1), date(2020, 9, 30))], 1):  # fmt: skip
        db.add(_fact("revenue", 20 + q, s, e, "quarterly", "0000000905-21-000001", "10-K",
                     date(2021, 3, 1)))  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/statements/income?period=quarterly",
                      headers=auth).json()  # fmt: skip
    keys = [c["key"] for c in body["columns"]]
    assert keys == [
        "Q2 FY2020",
        "Q3 FY2020",
        "Transition Q1 (ended 2021-03-31)",
        "Transition Q2 (ended 2021-06-30)",
        "Transition Q3 (ended 2021-09-30)",
    ]
    assert len(set(keys)) == len(keys)
    assert all(c["transition"] for c in body["columns"] if c["key"].startswith("Transition"))


def test_a_reports_run_of_years_brings_old_years_and_the_transition(client, auth, db):
    """Cenntro: its report for January 2018 presents a 7-month transition to January 2017 and
    the June 2016 and 2015 years before it; all are columns. A balance at the transition's end
    is a column too (Best Buy's 11-month year to Feb 2, 2013); one at another date is not."""
    now = datetime.now(UTC)
    cik = "0000000909"
    db.add(Company(cik=cik, legal_name="CENNTRO", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now,
                   quality_status="ok"))  # fmt: skip
    r, filed = "0000000909-18-000001", date(2018, 4, 30)
    rows = [
        ("revenue", 50, date(2014, 7, 1), date(2015, 6, 30), "annual"),
        ("revenue", 60, date(2015, 7, 1), date(2016, 6, 30), "annual"),
        ("revenue", 35, date(2016, 7, 1), date(2017, 1, 31), "ytd"),
        ("revenue", 70, date(2017, 2, 1), date(2018, 1, 31), "annual"),
        ("total_assets", 500, None, date(2016, 6, 30), "annual"),
        ("total_assets", 520, None, date(2017, 1, 31), "annual"),
        ("total_assets", 540, None, date(2017, 7, 31), "annual"),  # an interim balance
        ("total_assets", 560, None, date(2018, 1, 31), "annual"),
    ]
    for metric, v, start, end, cls in rows:
        f = _fact(metric, v, start, end, cls, r, "20-F", filed)
        f.cik = cik
        if start is None:
            f.period_type = "instant"
        db.add(f)
    db.commit()
    from app.services import fiscal_years

    ends = fiscal_years.own_year_ends(db, [cik])[cik]
    from sqlalchemy import select

    db.scalar(select(Company).where(Company.cik == cik)).fiscal_year_ends = ",".join(
        e.isoformat() for e in ends
    )
    db.commit()
    inc = client.get(f"/v1/companies/{cik}/statements/income?period=annual", headers=auth).json()
    assert [c["key"] for c in inc["columns"]] == [
        "FY2015",
        "FY2016",
        "Transition period (7 months, ended 2017-01-31)",
        "FY2018",
    ]
    bal = client.get(f"/v1/companies/{cik}/statements/balance?period=annual",
                     headers=auth).json()  # fmt: skip
    assert [c["period_end"] for c in bal["columns"]] == ["2016-06-30", "2017-01-31",
                                                        "2018-01-31"]  # fmt: skip


def test_a_predecessor_and_successor_year_is_not_a_transition(db):
    """Frontier: December years; on emerging in 2021 its report shows a predecessor's four
    months to April 30 and a successor's eight from May 1. The year end never changed: no
    transition, whichever part is short."""
    now = datetime.now(UTC)
    cik = "0000000910"
    db.add(Company(cik=cik, legal_name="FRONTIER", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now,
                   quality_status="ok"))  # fmt: skip
    r = "0000000910-23-000001"
    for v, start, end, cls in [
        (80, date(2020, 1, 1), date(2020, 12, 31), "annual"),
        (25, date(2021, 1, 1), date(2021, 4, 30), "other"),
        (50, date(2021, 5, 1), date(2021, 12, 31), "other"),
        (78, date(2022, 1, 1), date(2022, 12, 31), "annual"),
    ]:
        f = _fact("revenue", v, start, end, cls, r, "10-K", date(2023, 2, 28))
        f.cik = cik
        db.add(f)
    db.commit()
    from app.services import fiscal_years

    assert fiscal_years.transitions(db, [cik]) == {}


def test_a_recast_calendar_quarter_is_not_a_transition_quarter(client, auth, db):
    """Pandora-like: a 10-KT from January to September 2021 (CHANGER's) with its quarters to
    March and June, and a later report's recast quarters, one starting before the transition
    and one inside it but out of its sequence: neither is a transition quarter."""
    _seed(db)
    t, later = "0000000905-21-000009", "0000000905-22-000001"
    for v, s, e, acc in [(31, date(2021, 1, 1), date(2021, 3, 31), t),
                         (32, date(2021, 4, 1), date(2021, 6, 30), t),
                         (33, date(2020, 12, 1), date(2021, 2, 28), later),
                         (34, date(2021, 3, 1), date(2021, 5, 31), later)]:  # fmt: skip
        db.add(_fact("revenue", v, s, e, "quarterly", acc, "10-KT" if acc == t else "10-K",
                     date(2022, 12, 1)))  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/statements/income?period=quarterly",
                      headers=auth).json()  # fmt: skip
    cols = {c["period_end"]: (c["key"], c["transition"]) for c in body["columns"]}
    assert cols["2021-03-31"] == ("Transition Q1 (ended 2021-03-31)", True)
    assert cols["2021-06-30"] == ("Transition Q2 (ended 2021-06-30)", True)
    assert cols["2021-02-28"][1] is False and cols["2021-05-31"][1] is False
    assert len({k for k, _ in cols.values()}) == len(cols)


def test_one_balance_column_per_year_end(client, auth, db):
    """S-07b: LATAM-like adoption-date balances at January 1 and 4, 2018 beside the December
    31, 2017 balance sheet are not columns; where a restated opening balance at January 1, 2019
    is the full balance sheet and December 31, 2018 has only a cash figure (Avino), the full
    one is the column. No year end loses its column."""
    now = datetime.now(UTC)
    cik = "0000000911"
    db.add(Company(cik=cik, legal_name="AEROLINEA", fiscal_year_end="1231",
                   fiscal_year_ends="2017-12-31,2018-12-31,2019-12-31",
                   source_url="https://www.sec.gov/", first_detected_at=now,
                   last_processed_at=now, quality_status="ok"))  # fmt: skip
    acc = "0000000911-20-000001"
    rows = [("total_assets", 100, date(2017, 12, 31)),
            ("total_liabilities", 60, date(2017, 12, 31)),
            ("cash_and_equivalents", 9, date(2017, 12, 31)),
            ("total_assets", 104, date(2018, 1, 1)), ("total_liabilities", 64, date(2018, 1, 4)),
            ("cash_and_equivalents", 11, date(2018, 12, 31)),
            ("total_assets", 120, date(2019, 1, 1)), ("total_liabilities", 70, date(2019, 1, 1)),
            ("total_assets", 130, date(2019, 12, 31)),
            ("total_liabilities", 75, date(2019, 12, 31))]  # fmt: skip
    for metric, v, end in rows:
        f = _fact(metric, v, None, end, "annual", acc, "20-F", date(2020, 4, 30))
        f.cik, f.period_type = cik, "instant"
        db.add(f)
    db.commit()
    bal = client.get(f"/v1/companies/{cik}/statements/balance?period=annual",
                     headers=auth).json()  # fmt: skip
    assert [(c["key"], c["period_end"]) for c in bal["columns"]] == [
        ("FY2017", "2017-12-31"), ("FY2018", "2019-01-01"), ("FY2019", "2019-12-31")]  # fmt: skip
    (assets,) = [r for r in bal["rows"] if r["metric"] == "total_assets"]
    assert [c["value"] for c in assets["cells"]] == [100, 120, 130]


def test_the_marts_leave_out_an_adoption_date_balance(db):
    """S-07b in the marts: a January 1, 2018 adoption-date balance is neither a second FY2017
    row nor the FY2017 company year (which kept the later period end and lost its revenue), nor
    the company's latest total assets."""
    import json

    from app.db.models import MartCompany, MartCompanyPeriod, MartFinancial
    from app.services import marts

    now = datetime.now(UTC)
    cik = "0000000912"
    db.add(Company(cik=cik, legal_name="ADOPTER INC", fiscal_year_end="1231",
                   fiscal_year_ends="2016-12-31,2017-12-31", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now,
                   quality_status="ok"))  # fmt: skip
    acc = "0000000912-18-000001"
    for metric, v, start, end in [
        ("revenue", 500, date(2017, 1, 1), date(2017, 12, 31)),
        ("total_assets", 900, None, date(2017, 12, 31)),
        ("total_liabilities", 400, None, date(2017, 12, 31)),
        ("total_assets", 905, None, date(2018, 1, 1)),  # ASC 606 opening balance
    ]:
        f = _fact(metric, v, start, end, "annual", acc, "10-K", date(2018, 2, 28))
        f.cik = cik
        if start is None:
            f.period_type = "instant"
        db.add(f)
    db.commit()
    marts.build_financial_marts(db, [cik])
    marts.build_company_marts(db, [cik])
    ends = {r.period_end for r in db.query(MartFinancial).filter(MartFinancial.cik == cik)}
    assert ends == {date(2017, 12, 31)}
    year = db.get(MartCompanyPeriod, (cik, 2017))
    assert year.period_end == date(2017, 12, 31) and year.revenue == 500
    assert year.total_assets == 900
    latest = json.loads(db.get(MartCompany, cik).latest_annual)
    assert latest["total_assets"]["period_end"] == "2017-12-31"


def test_a_company_year_keeps_its_income_and_balance_sheet(db):
    """S-07b in the marts, Delta Tucker-like: its 2011 durations are dated December 30 (three
    figures) with a repeat at December 31, its balances at both (more at December 31). One end
    is chosen per period type, and the company year holds both, not balances alone."""
    from app.db.models import MartCompanyPeriod
    from app.services import marts

    now = datetime.now(UTC)
    cik = "0000000913"
    db.add(Company(cik=cik, legal_name="TUCKER", fiscal_year_end="1231",
                   fiscal_year_ends="2010-12-31,2011-12-31", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now,
                   quality_status="ok"))  # fmt: skip
    acc = "0000000913-12-000001"
    d30, d31 = date(2011, 12, 30), date(2011, 12, 31)
    for metric, v, start, end in [
        ("revenue", 370, date(2011, 1, 1), d30), ("net_income", -6, date(2011, 1, 1), d30),
        ("operating_cash_flow", 17, date(2011, 1, 1), d30),
        ("revenue", 370, date(2010, 12, 31), d31),
        ("total_assets", 201, None, d30),
        ("total_assets", 201, None, d31), ("total_liabilities", 150, None, d31),
    ]:  # fmt: skip
        f = _fact(metric, v, start, end, "annual", acc, "10-K", date(2012, 3, 30))
        f.cik = cik
        if start is None:
            f.period_type = "instant"
        db.add(f)
    db.commit()
    marts.build_financial_marts(db, [cik])
    year = db.get(MartCompanyPeriod, (cik, 2011))
    assert year.period_end == d31
    assert (year.revenue, year.net_income, year.total_assets) == (370, -6, 201)


def test_a_new_reporting_currency_keeps_its_opening_balance(db):
    """S-07b per unit, BELLUS Health-like: Canadian dollar balances at December 31, 2018 and,
    after the move to US dollars, a dollar opening balance at January 1, 2019. The dollar
    company year 2018 keeps its total assets."""
    from app.db.models import MartCompanyPeriod
    from app.services import marts

    now = datetime.now(UTC)
    cik = "0000000914"
    db.add(Company(cik=cik, legal_name="BIOTECH CANADA", fiscal_year_end="1231",
                   fiscal_year_ends="2018-12-31,2019-12-31", source_url="https://www.sec.gov/",
                   first_detected_at=now, last_processed_at=now,
                   quality_status="ok"))  # fmt: skip
    old, new = "0000000914-19-000001", "0000000914-20-000001"
    for metric, v, unit, end, acc in [
        ("total_assets", 53, "CAD", date(2018, 12, 31), old),
        ("total_liabilities", 3, "CAD", date(2018, 12, 31), old),
        ("cash_and_equivalents", 15, "CAD", date(2018, 12, 31), old),
        ("total_assets", 39, "USD", date(2019, 1, 1), new),
        ("total_liabilities", 2, "USD", date(2019, 1, 1), new),
        ("total_assets", 120, "USD", date(2019, 12, 31), new),
    ]:
        f = _fact(metric, v, None, end, "annual", acc, "40-F", date(2020, 3, 1))
        f.cik, f.unit, f.currency, f.period_type = cik, unit, unit, "instant"
        db.add(f)
    db.commit()
    marts.build_financial_marts(db, [cik])
    year = db.get(MartCompanyPeriod, (cik, 2018))
    assert year is not None and year.total_assets == 39 and year.currency == "USD"
