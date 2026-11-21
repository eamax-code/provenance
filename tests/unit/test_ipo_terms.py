"""F-02: deal terms from the prospectus, each value with its verbatim evidence."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.services import ipo_terms

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "ipo"


def _read(name: str) -> str:
    return (FIX / name).read_text()


def test_anthropic_final_prospectus():
    f = ipo_terms.extract(
        _read("anthropic_424b4_cover.txt"), _read("anthropic_424b4_underwriting.txt"), "424B4",
        date(2026, 11, 19), _read("anthropic_424b4_summary.txt"),
    )  # fmt: skip
    v = {k: x["value"] for k, x in f.items()}
    assert v["price_final"] == 83.0 and v["currency"] == "USD"
    assert v["shares_offered"] == 980_000_000
    assert v["shares_primary"] == 956_351_354 and v["shares_secondary"] == 23_648_646
    assert v["gross_proceeds"] == 81_340_000_000
    assert v["underwriting_discount_total"] == 550_000_000
    assert v["exchange"] == "Nasdaq Global Select Market" and v["ticker"] == "ANT"
    assert v["closing_date"] == "2026-11-20"
    assert v["lead_underwriters"] == ["Goldman Sachs & Co. LLC", "Morgan Stanley & Co. LLC"]
    assert len(v["underwriters"]) == 22 and "Total" not in v["underwriters"]
    assert v["lockup_days"] == 180 and v["lockup_days_max"] == 365
    assert v["lockup_expiry"] == "2027-05-18" and f["lockup_expiry"]["derived"] is True
    assert v["quiet_period_end"] == "2026-12-14" and f["quiet_period_end"]["derived"] is True
    # every value carries its words from the filing
    assert "$83.00" in f["price_final"]["evidence"]
    assert "under the symbol" in f["ticker"]["evidence"]
    assert all(x["evidence"] for x in f.values())
    assert not any(
        x["derived"] for k, x in f.items() if k not in ("lockup_expiry", "quiet_period_end")
    )


def test_registration_amendment_gives_the_range_and_no_derived_dates():
    cover = (
        "This is an initial public offering of shares of common stock of Example Labs, Inc. "
        "We are offering 10,000,000 shares of our common stock. It is currently estimated that "
        "the initial public offering price will be between $14.00 and $16.00 per share. We have "
        "applied to list our common stock on the New York Stock Exchange under the symbol “EXL.”"
    )
    f = ipo_terms.extract(cover, "", "S-1/A", date(2026, 10, 1))
    v = {k: x["value"] for k, x in f.items()}
    assert (v["price_low"], v["price_high"]) == (14.0, 16.0) and "price_final" not in v
    assert v["exchange"] == "New York Stock Exchange" and v["ticker"] == "EXL"
    assert v["shares_primary"] == 10_000_000
    assert "lockup_expiry" not in v and "quiet_period_end" not in v  # only after pricing
    assert ipo_terms.flat(f)["price_low"] == 14.0 and ipo_terms.flat(None)["price_final"] is None
    # Anthropic's last S-1/A words it without "per share" after the range
    anthropic = ("It is currently estimated that the initial public offering price per share will "
                 "be \nbetween $70.00 and $78.00 . We have been approved to list")  # fmt: skip
    g = ipo_terms.extract(anthropic, "", "S-1/A")
    assert (g["price_low"]["value"], g["price_high"]["value"]) == (70.0, 78.0)


def test_nothing_without_evidence():
    assert ipo_terms.extract("Our company makes widgets.", "", "424B4", date(2026, 1, 1)) == {
        "quiet_period_end": {
            "value": "2026-01-26",
            "evidence": "Derived: prospectus dated 2026-01-01 plus 25 days (FINRA Rule 2241 "
            "research quiet period)",
            "derived": True,
        }
    }


def test_chat_answer_cites_every_line():
    f = ipo_terms.extract(
        _read("anthropic_424b4_cover.txt"), _read("anthropic_424b4_underwriting.txt"), "424B4",
        date(2026, 11, 19), _read("anthropic_424b4_summary.txt"),
    )  # fmt: skip
    url = "https://www.sec.gov/Archives/edgar/data/2130357/x-424b4.htm"
    terms = {k: {**v, "form_type": "424B4", "filing_date": "2026-11-19", "source_url": url}
             for k, v in f.items()}  # fmt: skip
    terms["price_low"] = {
        "value": 70.0,
        "evidence": "...",
        "derived": False,
        "form_type": "S-1/A",
        "filing_date": "2026-11-17",
        "source_url": "https://www.sec.gov/Archives/edgar/data/2130357/a.htm",
    }
    terms["price_high"] = {**terms["price_low"], "value": 78.0}
    text, cites = ipo_terms.chat_answer("Anthropic", terms)
    assert text.startswith("Anthropic priced its IPO at $83.00 a share")
    assert "above the $70.00 to $78.00 range in its amended registration statement (S-1/A)" in text
    assert "19 Nov 2026" in text and "18 May 2027" in text and "derived" in text
    assert [c["label"] for c in cites] == ["424B4 filed 19 Nov 2026", "S-1/A filed 17 Nov 2026"]
    assert text.count("[1]") + text.count("[2]") == 7  # price, range, shares, proceeds, leads,
    # listing and lock-up each cite their filing
    assert ipo_terms.is_terms_question("Who underwrote Anthropic?")
    assert not ipo_terms.is_terms_question("What are Anthropic's IPO risk factors?")
