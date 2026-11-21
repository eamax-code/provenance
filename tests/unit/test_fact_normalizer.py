from datetime import date
from decimal import Decimal

from app.services.fact_normalizer import (
    CONCEPT_MAP,
    MAPPING_VERSION,
    METRIC_LABELS,
    SUPPORTED_METRICS,
    classify_duration,
    currency_from_unit,
    default_unit,
    derive_quarters,
    normalize_company_facts,
    unit_kind,
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
    assert currency_from_unit("shares") is None and currency_from_unit("pure") is None
    # a per-share figure carries its currency (1.3.0)
    assert currency_from_unit("USD/shares") == "USD" and currency_from_unit("EUR/shares") == "EUR"


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


def test_later_restatement_does_not_change_earlier_filing_quality(facts_aapl):
    """Conflicts are judged per filing, so as_of answers keep the status true at the time."""
    import copy

    payload = copy.deepcopy(facts_aapl)
    tag = "RevenueFromContractWithCustomerExcludingAssessedTax"
    for obs in payload["facts"]["us-gaap"][tag]["units"]["USD"]:
        if obs["end"] == "2023-09-30" and obs["accn"] == "0000320193-24-000123":
            obs["val"] = 383_000_000_000  # the 2024 10-K restates only the preferred tag
    facts = normalize_company_facts(payload, "0000320193")
    fy23 = {
        f.accession_number: f.quality_status
        for f in _by(facts, "revenue", period_end=date(2023, 9, 30), source_tag=tag)
    }
    assert fy23 == {"0000320193-23-000106": "ok", "0000320193-24-000123": "ok"}

    # Tags that disagree inside one filing are still flagged.
    for obs in payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"]:
        obs["val"] = 1
    facts = normalize_company_facts(payload, "0000320193")
    original = _by(
        facts, "revenue", period_end=date(2023, 9, 30), accession_number="0000320193-23-000106"
    )
    assert {f.quality_status for f in original} == {"ambiguous_mapping"}


def test_twelve_months_in_a_quarterly_report_is_ttm_not_annual():
    """Amazon's 10-Qs report net income for the twelve months to the quarter end (mapping 1.2.0)."""
    payload = {
        "cik": 1018724,
        "entityName": "AMAZON COM INC",
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"start": "2025-10-01", "end": "2026-09-30", "val": 134779000000,
                             "accn": "0001018724-26-000040", "fy": 2026, "fp": "Q3",
                             "form": "10-Q", "filed": "2026-10-30"},
                            {"start": "2025-01-01", "end": "2025-12-31", "val": 77670000000,
                             "accn": "0001018724-26-000004", "fy": 2025, "fp": "FY",
                             "form": "10-K", "filed": "2026-02-06"},
                        ]
                    }
                }
            }
        },
    }  # fmt: skip
    facts = {f.period_end: f for f in normalize_company_facts(payload, "0001018724")}
    assert facts[date(2026, 9, 30)].period_class == "ttm"
    assert facts[date(2025, 12, 31)].period_class == "annual"


def _obs(val, end, start=None, accn="0000320193-25-000001", form="10-K", fp="FY"):
    o = {"val": val, "end": end, "accn": accn, "fy": 2025, "fp": fp, "form": form,
         "filed": "2025-11-01"}  # fmt: skip
    if start:
        o["start"] = start
    return o


def _payload(tags):
    return {"facts": {"us-gaap": {t: {"units": u} for t, u in tags.items()}}}


def test_thirty_metrics_each_with_label_unit_and_statement():
    assert len(SUPPORTED_METRICS) == 30 and MAPPING_VERSION == "1.3.0"
    for metric, spec in CONCEPT_MAP.items():
        assert METRIC_LABELS[metric] and spec["statement"] in ("income", "balance", "cash_flow")
        assert spec["unit"] in ("currency", "per_share", "shares")
        assert spec["period_type"] == ("instant" if spec["statement"] == "balance" else "duration")
        tags = spec["candidates"] + spec["fallbacks"]
        assert len(tags) == len(set(tags)), metric
    assert default_unit("eps_diluted") == "USD/shares" and default_unit("revenue") == "USD"
    assert default_unit("shares_basic_weighted") == "shares"
    assert unit_kind("USD/shares") == "per_share" and unit_kind("pure") is None


def test_eps_and_shares_are_mapped_with_their_units():
    year = {"start": "2024-09-29"}
    facts = normalize_company_facts(
        _payload({
            "EarningsPerShareDiluted": {"USD/shares": [_obs(8.98, "2025-09-27", **year)]},
            "WeightedAverageNumberOfSharesOutstandingBasic": {
                "shares": [_obs(14661935000, "2025-09-27", **year)]
            },
        }),
        "320193",
    )  # fmt: skip
    eps = _by(facts, "eps_diluted")[0]
    assert eps.value == Decimal("8.98") and eps.currency == "USD" and eps.quality_status == "ok"
    shares = _by(facts, "shares_basic_weighted")[0]
    assert shares.unit == "shares" and shares.currency is None and shares.quality_status == "ok"


def test_a_metric_reported_in_the_wrong_unit_kind_is_ambiguous():
    facts = normalize_company_facts(
        _payload({"EarningsPerShareBasic": {"USD": [_obs(9.01, "2025-09-27", "2024-09-29")]}}),
        "320193",
    )
    eps = _by(facts, "eps_basic")[0]
    assert eps.quality_status == "ambiguous_mapping"
    assert any("not the per_share unit" in n for n in eps.notes)


def test_industry_fallback_fills_a_gap_but_never_overrides_or_conflicts():
    # A utility: contract revenue (primary) and regulated-plus-unregulated revenue (fallback)
    # disagree in the same filing; the primary stays ok, the fallback is the alternate.
    start, end = "2025-01-01", "2025-12-31"
    facts = normalize_company_facts(
        _payload({
            "RevenueFromContractWithCustomerIncludingAssessedTax": {
                "USD": [_obs(31741000000, end, start)]
            },
            "RegulatedAndUnregulatedOperatingRevenue": {
                "USD": [_obs(32237000000, end, start), _obs(29060000000, "2024-12-31",
                                                           "2024-01-01")]
            },
        }),
        "1326160",
    )  # fmt: skip
    rev = _by(facts, "revenue", period_end=date(2025, 12, 31))
    primary = next(f for f in rev if f.source_tag.startswith("RevenueFromContract"))
    fallback = next(f for f in rev if f.source_tag.startswith("Regulated"))
    assert primary.quality_status == "ok"
    assert fallback.quality_status == "ambiguous_mapping"
    assert any("industry fallback" in n for n in fallback.notes)
    # a year only the fallback covers is used as reported
    gap = _by(facts, "revenue", period_end=date(2024, 12, 31))
    assert len(gap) == 1 and gap[0].quality_status == "ok"


def test_bank_interest_expense_uses_the_2024_operating_tag_when_alone():
    facts = normalize_company_facts(
        _payload({"InterestExpenseOperating": {"USD": [_obs(97898000000, "2025-12-31",
                                                            "2025-01-01")]}}),
        "19617",
    )  # fmt: skip
    f = _by(facts, "interest_expense")[0]
    assert f.quality_status == "ok" and f.source_tag == "InterestExpenseOperating"
