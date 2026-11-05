from datetime import date

from app.services import periods


def test_fiscal_years_and_quarters():
    # Apple: year ends late September; the December quarter opens the next fiscal year.
    assert periods.label(date(2025, 9, 27), "annual", "0926") == "FY2025"
    assert periods.label(date(2025, 12, 27), "quarterly", "0926") == "Q1 FY2026"
    assert periods.label(date(2026, 6, 27), "quarterly", "0926") == "Q3 FY2026"
    # Microsoft: June year end.
    assert periods.label(date(2026, 6, 30), "annual", "0630") == "FY2026"
    assert periods.label(date(2025, 9, 30), "quarterly", "0630") == "Q1 FY2026"
    # Walmart: January year end, named by the year it ends in.
    assert periods.label(date(2026, 1, 31), "annual", "0131") == "FY2026"
    assert periods.label(date(2025, 4, 30), "quarterly", "0131") == "Q1 FY2026"
    # 52/53-week years ending in the first days of January belong to the year before.
    assert periods.label(date(2022, 1, 1), "annual", "0102") == "FY2021"
    assert periods.label(date(2022, 12, 31), "annual", "0102") == "FY2022"
    assert periods.label(date(2026, 1, 3), "quarterly", "1231") == "Q4 FY2025"
    # Calendar companies and a missing year end.
    assert periods.label(date(2025, 12, 31), "annual", "1231") == "FY2025"
    assert periods.label(date(2025, 3, 31), "quarterly", None) == "Q1 FY2025"


def test_a_change_of_year_end_names_the_month():
    ends = [date(2014, 12, 31), date(2015, 9, 30), date(2015, 12, 31), date(2016, 12, 31)]
    assert periods.labels(ends, "annual", "1231") == [
        "FY2014",
        "FY2015 (Sep)",
        "FY2015 (Dec)",
        "FY2016",
    ]
    advance = [date(2021, 1, 2), date(2022, 1, 1), date(2022, 12, 31)]
    assert periods.labels(advance, "annual", "1231") == ["FY2020", "FY2021", "FY2022"]
