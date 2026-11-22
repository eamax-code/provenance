"""Form 4 owner names: cased in filed order, never reordered (PM, 2026-11-23)."""

import pytest

from app.services.chat_intents import filed_owner_name


@pytest.mark.parametrize(
    ("filed", "shown"),
    [
        ("LEVINSON ARTHUR D", "Levinson Arthur D"),
        ("COOK TIMOTHY D.", "Cook Timothy D."),
        ("SMITH JOHN JR", "Smith John JR"),
        ("SMITH JOHN JR.", "Smith John JR."),
        ("WU TIM III", "Wu Tim III"),
        ("LEE JOHN", "Lee John"),  # a short surname is a name, not an acronym
        ("O'BRIEN MARY-KATE", "O'Brien Mary-Kate"),
        ("KKR & CO. L.P.", "KKR & Co. L.P."),  # a firm follows filed_name
        ("BERKSHIRE HATHAWAY INC", "Berkshire Hathaway Inc"),
        ("Jeffrey P. Bezos", "Jeffrey P. Bezos"),  # mixed case stays exactly as filed
        (None, None),
    ],
)
def test_filed_owner_name(filed, shown):
    assert filed_owner_name(filed) == shown
