"""K-04b: former tickers dated from the trading symbols companies tag on their own filings."""

from __future__ import annotations

from datetime import date

from app.db.models import CompanyAlias
from app.services import ticker_history

CIK = "0000320193"


def _row(symbol, filed, title="Common Stock, $0.00001 par value", cik=CIK):
    return {
        "accession_number": f"x-{symbol}-{filed}", "cik": cik, "form_type": "10-Q",
        "filed_date": filed, "symbol": symbol, "exchange": "NASDAQ", "title": title,
    }  # fmt: skip


ROWS = [
    _row("APPL", date(2021, 5, 1)),
    _row("APPL", date(2022, 2, 1)),
    _row("AAPL", date(2023, 2, 1)),  # current: never a former ticker
    _row("AAPL26", date(2023, 2, 1), title="1.375% Notes due 2026"),  # debt: left out
    _row("N/A", date(2021, 5, 1)),  # placeholder
]


def test_segments_keep_equity_symbols_with_their_dates():
    assert ticker_history.dated(ROWS, CIK) == [
        ("APPL", date(2021, 5, 1), date(2022, 2, 1)),
        ("AAPL", date(2023, 2, 1), date(2023, 2, 1)),
    ]
    assert ticker_history.norm("brk.b") == "BRK-B"


def test_apply_stores_former_tickers_and_widens_known_ones(db, ingested_aapl):
    out = ticker_history.apply(db, ROWS)
    assert out["former_tickers_added"] == 1
    row = db.get(CompanyAlias, (CIK, "APPL"))
    assert row.kind == "former_ticker" and (row.valid_from, row.valid_to) == (
        date(2021, 5, 1),
        date(2022, 2, 1),
    )
    assert db.get(CompanyAlias, (CIK, "AAPL")) is None
    assert db.get(CompanyAlias, (CIK, "AAPL26")) is None
    later = ticker_history.apply(db, [_row("APPL", date(2022, 8, 1))])
    assert later == {"companies": 1, "former_tickers_added": 0, "widened": 1}
    assert db.get(CompanyAlias, (CIK, "APPL")).valid_to == date(2022, 8, 1)


def test_search_finds_the_company_by_a_dated_former_ticker(db, client, auth, ingested_aapl):
    ticker_history.apply(db, ROWS)
    r = client.get("/v1/companies/search?q=APPL", headers=auth).json()
    assert r["data"][0]["cik"] == CIK


def test_display_names_k06():
    from app.services.intel import display_name

    assert display_name("TOYOTA MOTOR CORP/") == "Toyota Motor Corp"  # trailing slash dropped
    assert display_name("SAP SE", "SAP") == "SAP SE"  # the ticker word keeps its capitals
    assert display_name("APPLE COMPUTER INC/FA") == "Apple Computer Inc"
    # the company's own cover-page name, when written with real casing, wins
    assert display_name("APPLE INC", "AAPL", "Apple Inc.") == "Apple Inc."
    # an all-caps cover name says nothing about casing: the conformed name is used
    assert display_name("MICROSOFT CORP", "MSFT", "MICROSOFT CORPORATION") == "Microsoft Corp"
    # "/S" of a legal form is not a state suffix; words glued by the data sets get their space
    assert display_name("NOVO NORDISK A S", "NVO", "Novo Nordisk A/S") == "Novo Nordisk A/S"
    assert display_name("BANCO BRADESCO S/A") == "Banco Bradesco S/A"
    assert display_name("NIO Inc.", "NIO", "NIOInc.") == "NIO Inc."
    assert display_name("PDD Holdings Inc.", "PDD", "PDD HoldingsInc.") == "PDD Holdings Inc."
    assert display_name("X", None, "Stephenson Fournier, PLLC") == "Stephenson Fournier, PLLC"
    assert display_name("QUALCOMM INC/DE") == "Qualcomm Inc"  # a state suffix still goes


def test_a_registrant_name_glued_by_the_data_sets_is_stored_with_its_space(db, ingested_aapl):
    rows = [{**_row("AAPL", date(2025, 11, 1)), "registrant": "AppleInc."}]
    assert ticker_history.apply_registrant_names(db, rows) == 1
    from app.db.models import Company

    assert db.query(Company).filter(Company.cik == CIK).one().registrant_name == "Apple Inc."


def test_registrant_names_are_stored_as_filed(db, ingested_aapl):
    rows = [{**_row("AAPL", date(2025, 11, 1)), "registrant": "Apple Inc."},
            {**_row("AAPL", date(2024, 11, 1)), "registrant": "APPLE INC"}]  # fmt: skip
    assert ticker_history.apply_registrant_names(db, rows) == 1
    from app.db.models import Company

    c = db.query(Company).filter(Company.cik == CIK).one()
    assert c.registrant_name == "Apple Inc." and c.registrant_name_accession.startswith("x-AAPL")
    filed = ticker_history.legal_name_as_filed(c)
    assert filed["name"] == "Apple Inc." and filed["source"] == "dei:EntityRegistrantName"


def test_profile_and_overview_show_the_legal_name_as_filed(db, client, auth, ingested_aapl):
    from app.services import company_overview

    rows = [{**_row("AAPL", date(2025, 11, 1)), "registrant": "Apple Inc."}]
    ticker_history.apply_registrant_names(db, rows)
    c = client.get("/v1/companies/320193", headers=auth).json()
    assert c["legal_name_as_filed"]["name"] == "Apple Inc."
    p = client.get("/v1/companies/320193/profile", headers=auth).json()
    assert p["legal_name_as_filed"]["accession_number"].startswith("x-AAPL")
    o = company_overview.build(db, CIK)
    assert o["company"]["legal_name_as_filed"]["source"] == "dei:EntityRegistrantName"
