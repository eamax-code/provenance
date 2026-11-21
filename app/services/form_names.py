"""Plain names for SEC form codes and readable dates, shared by the profile summary, chat and
the filings lists (S-01), so every surface says "an annual report (10-K)" the same way."""

from __future__ import annotations

from datetime import date

FORM_NAMES: dict[str, str] = {
    "10-K": "annual report", "10-K/A": "amended annual report", "10-KT": "transition report",
    "10-Q": "quarterly report", "10-Q/A": "amended quarterly report",
    "20-F": "annual report", "20-F/A": "amended annual report", "40-F": "annual report",
    "6-K": "current report", "8-K": "current report", "8-K/A": "amended current report",
    "3": "initial insider holdings report", "4": "insider trade report",
    "5": "annual insider report", "3/A": "amended initial insider holdings report",
    "4/A": "amended insider trade report", "144": "notice of proposed sale",
    "DEF 14A": "proxy statement", "DEFA14A": "additional proxy material",
    "PRE 14A": "preliminary proxy statement", "DEFM14A": "merger proxy statement",
    "SC 13D": "5% holder report", "SC 13D/A": "amended 5% holder report",
    "SC 13G": "5% holder report", "SC 13G/A": "amended 5% holder report",
    "SCHEDULE 13D": "5% holder report", "SCHEDULE 13D/A": "amended 5% holder report",
    "SCHEDULE 13G": "5% holder report", "SCHEDULE 13G/A": "amended 5% holder report",
    "13F-HR": "institutional holdings report", "S-1": "registration statement",
    "S-1/A": "amended registration statement", "F-1": "registration statement",
    "F-1/A": "amended registration statement", "S-3": "shelf registration statement",
    "S-4": "merger registration statement", "S-8": "employee share plan registration",
    "424B4": "final prospectus", "424B3": "prospectus", "424B2": "prospectus supplement",
    "424B5": "prospectus supplement", "FWP": "free writing prospectus",
    "DRS": "confidential draft registration", "EFFECT": "notice of effectiveness",
    "8-A12B": "exchange listing registration", "8-A12G": "securities registration",
    "CERT": "exchange certification", "25-NSE": "notice of removal from listing",
    "25": "notice of removal from listing", "15-12G": "deregistration notice",
    "15-12B": "deregistration notice", "15-15D": "notice of suspension of reporting",
    "NT 10-K": "notice of late annual report", "NT 10-Q": "notice of late quarterly report",
    "SC TO-T": "tender offer statement", "RW": "registration withdrawal",
    "ARS": "annual report to shareholders",
}  # fmt: skip
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# codes said with "Form" in front of them
_FORM_WORD = {"3", "4", "5", "3/A", "4/A", "5/A", "144", "25", "25-NSE", "15-12B", "15-12G",
              "15-15D", "10", "10-12B", "10-12G"}  # fmt: skip


def _code(form: str) -> str:
    return f"Form {form}" if form.upper() in _FORM_WORD else form


def form_label(form: str | None) -> str:
    """ "Annual report (10-K)", "Insider trade report (Form 4)"; the code alone when unknown."""
    form = (form or "").strip()
    name = FORM_NAMES.get(form.upper())
    return f"{name[0].upper()}{name[1:]} ({_code(form)})" if name else _code(form)


def form_phrase(form: str | None) -> str:
    """ "an annual report (10-K)" for running text."""
    form = (form or "").strip()
    name = FORM_NAMES.get(form.upper())
    if not name:
        code = _code(form)
        # spoken letter by letter: "an N-PX", "an S-3ASR", "a DOS"
        spoken_an = code[:1].upper() in "AEFHILMNORSX8" and not code.startswith("Form")
        return f"{'an' if spoken_an else 'a'} {code} filing"
    return f"{'an' if name[0] in 'aeiou' else 'a'} {name} ({_code(form)})"


def human_date(d: date | str | None) -> str:
    """ "26 Sep 2026"; empty for no date."""
    if d is None:
        return ""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"
