from datetime import date
from decimal import Decimal

from app.services.fact_normalizer import (
    MAPPING_VERSION,
    classify_duration,
    currency_from_unit,
    derive_quarters,
    normalize_company_facts,
)


def _by(facts, metric, **kw):
    out = [
        f for f in facts if f.metric == metric and all(getattr(f, k) == v for k, v in kw.items())
    ]
    return out


def test_mapping_preserves_source_fields(facts_aapl):
    facts = normalize_company_facts(facts_aapl, "0000320193")
    rev = _by(
        facts,
        "revenue",
        period_end=date(2024, 9, 28),
        source_tag="RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert len(rev) == 1
    f = rev[0]
    assert f.value == Decimal("391035000000") and f.unit == "USD" and f.currency == "USD"
    assert (
        f.period_start == date(2023, 10, 1)
        and f.period_type == "duration"
        and f.period_class == "annual"
    )
    assert f.fiscal_year == 2024 and f.fiscal_period == "FY" and f.form_type == "10-K"
    assert f.accession_number == "0000320193-24-000123" and f.filed_date == date(2024, 11, 1)
    assert f.source_url.endswith("/0000320193-24-000123-index.html")
    assert f.mapping_version == MAPPING_VERSION and f.quality_status == "ok" and f.derived is False


def test_all_five_metrics_present(facts_aapl):
    facts = normalize_company_facts(facts_aapl, "0000320193")
    assert {f.metric for f in facts} == {
        "revenue",
        "operating_income",
        "net_income",
        "total_assets",
        "operating_cash_flow",
    }


def test_instant_facts_have_no_start(facts_aapl):
    facts = normalize_company_facts(facts_aapl, "0000320193")
    assets = _by(facts, "total_assets")
    assert all(f.period_type == "instant" and f.period_start is None for f in assets)
    annual = [f for f in assets if f.period_class == "annual"]
    quarterly = [f for f in assets if f.period_class == "quarterly"]
    assert {f.period_end for f in annual} == {date(2023, 9, 30), date(2024, 9, 28)}
    assert [f.period_end for f in quarterly] == [date(2024, 6, 29)]


def test_ytd_is_never_classified_as_quarter(facts_aapl):
    facts = normalize_company_facts(facts_aapl, "0000320193")
    ytd6 = _by(facts, "revenue", period_start=date(2023, 10, 1), period_end=date(2024, 3, 30))
    ytd9 = _by(facts, "revenue", period_start=date(2023, 10, 1), period_end=date(2024, 6, 29))
    assert ytd6[0].period_class == "ytd" and ytd9[0].period_class == "ytd"
    assert ytd6[0].fiscal_period == "Q2"  # SEC label retained but not trusted for duration
    q = _by(facts, "revenue", period_start=date(2023, 12, 31), period_end=date(2024, 3, 30))
    assert q[0].period_class == "quarterly"


def test_classify_duration_boundaries():
    assert classify_duration(date(2023, 1, 1), date(2023, 12, 31)) == "annual"
    assert classify_duration(date(2024, 1, 1), date(2024, 3, 31)) == "quarterly"
    assert classify_duration(date(2024, 1, 1), date(2024, 6, 30)) == "ytd"
    assert classify_duration(date(2024, 1, 1), date(2024, 1, 15)) == "other"
    assert classify_duration(date(2020, 1, 1), date(2024, 1, 1)) == "other"


def test_negative_values_and_missing_values(facts_msft):
    facts = normalize_company_facts(facts_msft, "0000789019")
    op = _by(facts, "operating_income")
    assert op[0].value == Decimal("-1000000")
    assets = _by(facts, "total_assets")
    invalid = [f for f in assets if f.quality_status == "invalid_source_value"]
    assert len(invalid) == 1 and invalid[0].value is None  # never zero
    assert "net_income" not in {f.metric for f in facts}  # absent stays absent


def test_unparseable_value_marked_invalid(facts_aapl):
    facts = normalize_company_facts(facts_aapl, "0000320193")
    bad = [f for f in _by(facts, "net_income") if f.accession_number == "0000320193-24-000999"]
    assert bad[0].quality_status == "invalid_source_value" and bad[0].value is None


def test_competing_tags_precedence_and_conflict(facts_aapl, facts_msft):
    # AAPL: both tags agree for FY2023 -> preferred ok, alternate ambiguous
    facts = normalize_company_facts(facts_aapl, "0000320193")
    fy23 = _by(facts, "revenue", period_start=date(2022, 9, 25), period_end=date(2023, 9, 30))
    pref = [
        f for f in fy23 if f.source_tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    ]
    alt = [f for f in fy23 if f.source_tag == "Revenues"]
    assert (
        all(f.quality_status == "ok" for f in pref) and alt[0].quality_status == "ambiguous_mapping"
    )
    # MSFT: tags disagree -> both ambiguous
    facts = normalize_company_facts(facts_msft, "0000789019")
    rev = _by(facts, "revenue")
    assert len(rev) == 2 and all(f.quality_status == "ambiguous_mapping" for f in rev)


def test_restatements_are_retained_as_separate_observations(facts_aapl):
    facts = normalize_company_facts(facts_aapl, "0000320193")
    fy23 = _by(
        facts,
        "revenue",
        period_start=date(2022, 9, 25),
        period_end=date(2023, 9, 30),
        source_tag="RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert {f.accession_number for f in fy23} == {"0000320193-23-000106", "0000320193-24-000123"}
    assert len({f.observation_key for f in fy23}) == 2


def test_partial_when_metadata_missing():
    payload = {
        "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"end": "2024-01-01", "val": 5}]}}}}
    }
    f = normalize_company_facts(payload, "1")[0]
    assert f.quality_status == "partial" and f.value == Decimal("5") and f.period_class == "other"


def test_malformed_payload_returns_empty():
    assert normalize_company_facts({}, "1") == []
    assert normalize_company_facts({"facts": "nope"}, "1") == []
    assert (
        normalize_company_facts(
            {"facts": {"us-gaap": {"Assets": {"units": {"USD": [{"val": 1}]}}}}}, "1"
        )
        == []
    )
    assert normalize_company_facts({"facts": {"us-gaap": {"Assets": {"units": "x"}}}}, "1") == []


def test_currency_from_unit():
    assert currency_from_unit("USD") == "USD" and currency_from_unit("EUR") == "EUR"
    assert currency_from_unit("shares") is None and currency_from_unit("USD/shares") is None


def test_derive_quarters_by_subtraction(facts_aapl):
    facts = normalize_company_facts(facts_aapl, "0000320193")
    derived = derive_quarters(facts)
    rev = [d for d in derived if d.metric == "revenue"]
    periods = {(d.period_start, d.period_end): d for d in rev}
    # Q4 FY24 = FY - 9M YTD
    q4 = periods[(date(2024, 6, 30), date(2024, 9, 28))]
    assert q4.value == Decimal("391035000000") - Decimal("296105000000")
    assert q4.derived is True and q4.quality_status == "derived" and q4.period_class == "quarterly"
    assert q4.derivation["minuend"]["accession_number"] == "0000320193-24-000123"
    assert q4.derivation["subtrahend"]["period_end"] == "2024-06-29"
    # Q3 = 9M - 6M ; Q2 = 6M - Q1 (Q1 reported standalone)
    assert periods[(date(2024, 3, 31), date(2024, 6, 29))].value == Decimal(
        "296105000000"
    ) - Decimal("210328000000")
    assert periods[(date(2023, 12, 31), date(2024, 3, 30))].value == Decimal(
        "210328000000"
    ) - Decimal("119575000000")
    # derived facts never feed further derivation and are never produced for instants
    assert all(d.period_type == "duration" for d in derived)
    assert derive_quarters(derived) == []
