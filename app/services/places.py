"""Where a registrant is (K-06): EDGAR's state/country codes. A US state or territory code means
the United States; EDGAR's codes for places abroad map to names (M0 Japan, 2M Germany, A6
Ontario, Canada); an unknown foreign code gives no country rather than a wrong one. The same
table as the company page (site/companies/page/page.js)."""

from __future__ import annotations

US = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR VI GU AS MP".split()
)
ABROAD = {
    "A0": "Alberta, Canada", "A1": "British Columbia, Canada", "A2": "Manitoba, Canada",
    "A3": "New Brunswick, Canada", "A4": "Newfoundland, Canada", "A5": "Nova Scotia, Canada",
    "A6": "Ontario, Canada", "A7": "Prince Edward Island, Canada", "A8": "Quebec, Canada",
    "A9": "Saskatchewan, Canada", "B0": "Yukon, Canada", "C3": "Australia", "D0": "Bermuda",
    "D5": "Brazil", "E9": "Cayman Islands", "F4": "China", "F5": "Taiwan", "G7": "Denmark",
    "I0": "France", "K3": "Hong Kong", "K7": "India", "L2": "Ireland", "L3": "Israel",
    "L6": "Italy", "M0": "Japan", "M5": "South Korea", "N4": "Luxembourg", "O5": "Mexico",
    "P7": "Netherlands", "U0": "Singapore", "U3": "Spain", "V7": "Sweden", "V8": "Switzerland",
    "X0": "United Kingdom", "2M": "Germany",
}  # fmt: skip
PLACEHOLDER_ZIPS = {"00000", "0000", "000000"}


def country_for(code: str | None) -> str | None:
    c = (code or "").strip().upper()
    if c in US:
        return "United States"
    return ABROAD.get(c)


def clean(address: dict) -> dict:
    """The address with its country from the code (never "United States" for a foreign code)
    and EDGAR's placeholder zip dropped."""
    out = dict(address)
    out["country"] = country_for(out.get("stateOrCountry"))
    if (out.get("zipCode") or "").strip() in PLACEHOLDER_ZIPS:
        out["zipCode"] = None
    return out
