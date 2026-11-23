"""K-06b: names filed in capitals read with real casing (2026-11-24, ui's examples)."""

from app.services.intel import display_name as d


def test_display_name_casing():
    assert d("JPMORGAN CHASE & CO", "JPM", "JPMORGAN CHASE & CO") == "JPMorgan Chase & Co"
    assert d("MCKESSON CORP", "MCK", "McKESSON CORPORATION") == "McKesson Corp"
    assert d("CVS HEALTH Corp", "CVS", "CVS HEALTH Corp") == "CVS Health Corp"
    assert d("UNITEDHEALTH GROUP INC", "UNH", None) == "UnitedHealth Group Inc"
    assert d("Cencora, Inc.", "COR", "Cencora,Inc.") == "Cencora, Inc."
    assert d("BP PLC", "BP") == "BP PLC" and d("EQUINOR ASA", "EQNR") == "Equinor ASA"
    assert d("HSBC HOLDINGS PLC", "HSBC") == "HSBC Holdings PLC"
    assert d("Apple Inc.", "AAPL", "Apple Inc.") == "Apple Inc."  # real casing as filed
    assert d("COSTCO WHOLESALE CORP /NEW", "COST") == "Costco Wholesale Corp"
