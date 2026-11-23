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


def test_casing_keeps_what_was_right():
    assert d("ABB LTD", "ABB", "ABB Ltd") == "ABB Ltd"  # an acronym beside a cased word
    assert d("CIFC Corp.", None, "CIFC Corp.") == "CIFC Corp."
    assert d("STORE Capital LLC") == "STORE Capital LLC"
    assert d("AT&T INC.", "T") == "AT&T Inc."
    assert d("MFS SERIES TRUST VII") == "MFS Series Trust VII"
    assert d("AGNICO EAGLE MINES LTD", "AEM") == "Agnico Eagle Mines Ltd"
    assert d("ST JOSEPH INC") == "St Joseph Inc"
    assert d("BANK OF AMERICA CORP", "BAC") == "Bank of America Corp"
    assert d("3M CO", "MMM") == "3M Co"
