from app.services.places import clean, country_for


def test_country_comes_from_the_code_not_a_default():
    assert country_for("M0") == "Japan" and country_for("2M") == "Germany"
    assert country_for("CA") == "United States" and country_for("A6") == "Ontario, Canada"
    assert country_for("Z9") is None and country_for(None) is None
    toyota = {"street1": "1 TOYOTA CHO", "city": "JAPAN", "stateOrCountry": "M0",
              "zipCode": "00000", "country": "United States"}  # fmt: skip
    fixed = clean(toyota)
    assert fixed["country"] == "Japan" and fixed["zipCode"] is None
