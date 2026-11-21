from datetime import date

from app.services.periods import calendar_period, parse_calendar_period


def test_calendar_period_follows_the_sec_frames():
    # Apple's frames in the SEC company facts
    assert calendar_period(date(2022, 9, 25), date(2023, 9, 30), "annual") == "CY2023"
    assert calendar_period(date(2023, 10, 1), date(2024, 9, 28), "annual") == "CY2024"
    assert calendar_period(date(2023, 10, 1), date(2023, 12, 30), "quarterly") == "CY2023Q4"
    assert calendar_period(date(2023, 12, 31), date(2024, 3, 30), "quarterly") == "CY2024Q1"
    assert calendar_period(None, date(2024, 9, 28), "annual") == "CY2024Q3I"
    assert calendar_period(date(2024, 1, 1), date(2024, 6, 30), "ytd") is None
    assert parse_calendar_period("cy2025q3") == (2025, 3, False)
    assert parse_calendar_period("CY2025") == (2025, None, False)
    assert parse_calendar_period("CY2025I") is None and parse_calendar_period("FY2025") is None
