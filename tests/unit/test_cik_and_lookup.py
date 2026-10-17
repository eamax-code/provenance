import pytest

from app.services.company_lookup import normalize_name, normalize_ticker, search_companies
from app.services.ingestion import import_ticker_mapping
from app.services.sec_client import filing_index_url, is_cik_like, normalize_cik


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("320193", "0000320193"),
        ("0000320193", "0000320193"),
        (320193, "0000320193"),
        ("CIK0000320193", "0000320193"),
        (" 1 ", "0000000001"),
    ],
)
def test_normalize_cik_valid(raw, expected):
    assert normalize_cik(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "12345678901", "0", "-5", "12.3", "AAPL"])
def test_normalize_cik_invalid(raw):
    with pytest.raises(ValueError):
        normalize_cik(raw)
    assert not is_cik_like(raw)


def test_filing_index_url_strips_leading_zeros_and_hyphens():
    url = filing_index_url("0000320193", "0000320193-24-000123")
    assert (
        url
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.html"
    )


def test_ticker_and_name_normalization():
    assert normalize_ticker(" brk.b ") == "BRK-B"
    assert normalize_name("  Apple   INC. ") == "apple inc."


def test_import_ticker_mapping_skips_bad_rows_and_dedups_by_cik(db, tickers_payload):
    stats = import_ticker_mapping(db, tickers_payload)
    db.commit()
    assert stats["rows"] == 6  # the "bad" row is dropped
    assert stats["companies"] == 5  # Alphabet has two share classes
    assert stats["inserted"] == 5
    again = import_ticker_mapping(db, tickers_payload)
    assert again["inserted"] == 0 and again["updated"] == 0


def test_search_by_cik_ticker_and_name(db, tickers_payload):
    import_ticker_mapping(db, tickers_payload)
    db.commit()
    hits, _ = search_companies(db, "320193")
    assert hits[0].company.cik == "0000320193" and hits[0].match_type == "cik"
    hits, _ = search_companies(db, "aapl")
    assert hits[0].match_type == "ticker" and hits[0].company.ticker == "AAPL"
    hits, _ = search_companies(db, "microsoft corp")
    assert hits[0].match_type == "name_exact"
    hits, _ = search_companies(db, "Micro")
    assert hits[0].match_type == "name_prefix"
    hits, _ = search_companies(db, "hathaway")
    assert hits[0].match_type == "name_contains"


def test_search_is_bounded_and_reports_has_more(db, tickers_payload):
    import_ticker_mapping(db, tickers_payload)
    db.commit()
    hits, has_more = search_companies(db, "inc", limit=2)
    assert len(hits) == 2 and has_more is True
    assert search_companies(db, "x" * 101) == ([], False)
    assert search_companies(db, "   ") == ([], False)


def test_search_escapes_like_wildcards(db, tickers_payload):
    import_ticker_mapping(db, tickers_payload)
    db.commit()
    hits, _ = search_companies(db, "%")
    assert hits == []
