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


def test_s07_a_year_is_named_by_its_own_end_and_a_quarter_by_the_year_containing_it():
    # Greif: its years end on October 31 though the stored year end says September 30
    assert periods.label(date(2019, 10, 31), "annual", ("0930", None, ())) == "FY2019"
    # Broadcom Corp: December years under a stale October year end
    assert periods.label(date(2014, 12, 31), "annual", ("1030", None, ())) == "FY2014"
    # Theralink: December years, then September from 2020; quarters follow the year in force
    conv = ("0930", None, (date(2018, 12, 31), date(2019, 12, 31), date(2020, 9, 30)))
    assert periods.label(date(2019, 9, 30), "quarterly", conv) == "Q3 FY2019"
    assert periods.label(date(2020, 6, 30), "quarterly", conv) == "Q3 FY2020"
    assert periods.label(date(2021, 3, 31), "quarterly", conv) == "Q2 FY2021"  # stored end
    # the S-05 offset still applies (Gap: start-year naming)
    assert periods.label(date(2026, 1, 31), "annual", ("0201", -1, ())) == "FY2025"


def test_s07_only_the_companys_own_years_are_fiscal_years():
    own = (date(2009, 12, 31), date(2010, 12, 31))
    assert periods.is_fiscal_year_end(date(2008, 12, 31), own)  # a comparative year
    assert periods.is_fiscal_year_end(date(2011, 1, 1), (date(2010, 1, 2),))  # 52/53 weeks
    assert not periods.is_fiscal_year_end(date(2010, 11, 30), (date(2010, 5, 31),
                                                                date(2011, 5, 31)))  # fmt: skip
    assert periods.is_fiscal_year_end(date(2010, 11, 30), ())  # nothing known: kept
    assert periods.transition_label(date(2015, 3, 1), date(2015, 12, 31)) == (
        "Transition period (10 months, ended 2015-12-31)"
    )
