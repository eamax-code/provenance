"""Typed events for filings (launch plan D-05): what a filing means, from its form and 8-K items.

A filing keeps one place in the event feed (kind "filing"); `event_types` lists what it means,
so a reader or a watch can ask for restatements or bankruptcies without parsing item codes.
Types come only from the form type and the 8-K item codes the filer declared on the cover; no
text is read and nothing is inferred. Backfill never notifies (ADR 0004), as for every filing.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_

from app.db.models import Filing
from app.services.form8k import split_items

EIGHT_K_FORMS = ("8-K", "8-K/A")


@dataclass(frozen=True)
class FilingEventType:
    label: str
    item: str | None = None  # 8-K item code
    forms: tuple[str, ...] = ()  # or one of these form types


FILING_EVENT_TYPES: dict[str, FilingEventType] = {
    "sec.restatement": FilingEventType(
        "Earlier financial statements should no longer be relied upon (8-K item 4.02)", "4.02"
    ),
    "sec.auditor_change": FilingEventType("Change of auditor (8-K item 4.01)", "4.01"),
    "sec.bankruptcy": FilingEventType("Bankruptcy or receivership (8-K item 1.03)", "1.03"),
    "sec.material_agreement": FilingEventType(
        "Material definitive agreement entered (8-K item 1.01)", "1.01"
    ),
    "sec.acquisition_completed": FilingEventType(
        "Acquisition or disposition of assets completed (8-K item 2.01)", "2.01"
    ),
    "sec.change_in_control": FilingEventType("Change in control (8-K item 5.01)", "5.01"),
    "sec.results": FilingEventType("Results of operations announced (8-K item 2.02)", "2.02"),
    "sec.shareholder_vote": FilingEventType(
        "Matters submitted to a shareholder vote (8-K item 5.07)", "5.07"
    ),
    "sec.late_filing": FilingEventType(
        "Notice of late annual or quarterly report (NT 10-K, NT 10-Q, NT 20-F)",
        forms=("NT 10-K", "NT 10-K/A", "NT 10-Q", "NT 10-Q/A", "NT 20-F", "NT 20-F/A"),
    ),
    "sec.deregistration": FilingEventType(
        "Deregistration of securities (Form 15)",
        forms=("15-12B", "15-12G", "15-15D", "15F-12B", "15F-12G", "15F-15D"),
    ),
    "sec.delisting": FilingEventType(
        "Removal from listing on an exchange (Form 25)", forms=("25", "25-NSE", "25/A")
    ),
    "sec.tender_offer": FilingEventType(
        "Third-party tender offer (Schedule TO-T)", forms=("SC TO-T", "SC14D1")
    ),
    "sec.merger_proxy": FilingEventType(
        "Definitive merger proxy or information statement (DEFM14A, DEFM14C)",
        forms=("DEFM14A", "DEFM14C"),
    ),
}


def types_for(form_type: str | None, items: str | list[str] | None) -> list[str]:
    """The event types a filing carries, in the order of FILING_EVENT_TYPES."""
    form = (form_type or "").upper()
    codes = set(split_items(items) if isinstance(items, str) or items is None else items)
    out = []
    for name, t in FILING_EVENT_TYPES.items():
        if t.item is not None:
            if form in EIGHT_K_FORMS and t.item in codes:
                out.append(name)
        elif form in t.forms:
            out.append(name)
    return out


def labels(types: list[str]) -> list[dict]:
    return [{"type": t, "label": FILING_EVENT_TYPES[t].label} for t in types]


def condition(types: list[str]):
    """SQL condition: filings carrying any of these event types."""
    clauses = []
    for name in types:
        t = FILING_EVENT_TYPES[name]
        if t.item is not None:
            clauses.append(Filing.form_type.in_(EIGHT_K_FORMS) & Filing.items.like(f"%{t.item}%"))
        else:
            clauses.append(Filing.form_type.in_(t.forms))
    return or_(*clauses)
