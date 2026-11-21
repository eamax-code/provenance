"""Leadership from two sources (launch plan K-02, U-03): Forms 3/4 say who reports as an
officer or director; 8-K item 5.02 says who was appointed, elected, or is leaving, and when.

A departure or retirement filed in an 8-K ends the person's insider role at once (or on its
effective date when that is later), instead of waiting two years without a Form 4. People are
matched across the two by last name and first initial ("COOK TIMOTHY D" and "Tim Cook").
"""

from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import OfficerChange
from app.services.officer_changes import CHANGE_LABELS, describe
from app.services.sec_client import filing_index_url

DEPARTING = ("departure", "retirement", "not_standing_for_reelection")
ARRIVING = ("appointment", "election")
ROLES = {
    "ceo": re.compile(r"chief executive|\bceo\b", re.I),
    "cfo": re.compile(r"chief financial|\bcfo\b|principal financial", re.I),
    # the board chair: not a vice chair, nor the chair of a committee
    "chair": re.compile(
        r"(?<!vice )(?<!vice-)\bchair(?:man|woman|person)?\b"
        r"(?! of the (?:audit|compensation|nominat))",
        re.I,
    ),
}
_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "md", "phd", "esq", "cpa"}
_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
PEOPLE_MAX = 12


def _tokens(name: str) -> list[str]:
    words = re.sub(r"[^A-Za-z\s\-']", " ", name or "").lower().split()
    return [w for w in words if w not in _SUFFIX and len(w) > 0]


def key_from_filed(name_as_filed: str) -> tuple[str, str] | None:
    """Forms 3/4 write names last name first: "COOK TIMOTHY D" -> ("cook", "t")."""
    t = _tokens(name_as_filed)
    return (t[0], t[1][0]) if len(t) >= 2 else None


def key_from_text(name: str | None) -> tuple[str, str] | None:
    """8-K text writes them first name first: "Timothy D. Cook" -> ("cook", "t")."""
    t = _tokens(name or "")
    return (t[-1], t[0][0]) if len(t) >= 2 else None


def effective_date(text: str | None) -> date | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").date()
    except ValueError:
        return None


def changes(db: Session, cik: str, as_of: date | None = None) -> list[OfficerChange]:
    stmt = select(OfficerChange).where(
        OfficerChange.cik == cik, OfficerChange.person.is_not(None),
        OfficerChange.change_type.in_(DEPARTING + ARRIVING + ("role_change",)),
    )  # fmt: skip
    if as_of:
        stmt = stmt.where(OfficerChange.filing_date <= as_of)
    return list(db.scalars(stmt.order_by(OfficerChange.filing_date, OfficerChange.seq)))


def _status(events: list[OfficerChange], today: date) -> tuple[str, date | None, OfficerChange]:
    """("departed" | "leaving" | "appointed" | "in office", leaving date, the deciding event)."""
    last = events[-1]
    if last.change_type in DEPARTING:
        when = effective_date(last.effective)
        if when and when > today:
            return "leaving", when, last
        return "departed", None, last
    if last.change_type in ARRIVING:
        return "appointed", None, last
    return "in office", None, last


def apply_to_roles(db: Session, cik: str, owners: list[dict], as_of: date | None = None) -> None:
    """K-02: end the insider role of anyone an 8-K says has left (in place on roles() output)."""
    today = as_of or date.today()
    by_key: dict[tuple, list[OfficerChange]] = {}
    for c in changes(db, cik, as_of):
        k = key_from_text(c.person)
        if k:
            by_key.setdefault(k, []).append(c)
    for o in owners:
        if o.get("kind") != "person":
            continue
        events = by_key.get(key_from_filed(o["name_as_filed"]) or ("", ""))
        if not events:
            continue
        status, leaving, ev = _status(events, today)
        if status == "departed" and o["current"]:
            o["current"] = False
            o["ended"] = {"date": (effective_date(ev.effective) or ev.filing_date).isoformat(),
                          "basis": "8-K item 5.02", "source_url": ev.source_url}  # fmt: skip
        elif status == "leaving":
            o["leaving_on"] = leaving.isoformat()


def overview(db: Session, cik: str, owners: list[dict], as_of: date | None = None) -> dict:
    """U-03: people grouped with their 8-K events newest first, and the current CEO, CFO and
    chair. `owners` is insiders.roles() output after apply_to_roles()."""
    today = as_of or date.today()
    owner_by_key = {
        key_from_filed(o["name_as_filed"]): o for o in owners if o.get("kind") == "person"
    }
    groups: dict[tuple, list[OfficerChange]] = {}
    for c in changes(db, cik, as_of):
        k = key_from_text(c.person)
        if k:
            groups.setdefault(k, []).append(c)
    people = []
    for k, events in groups.items():
        status, leaving, ev = _status(events, today)
        o = owner_by_key.get(k)
        current = status in ("appointed", "leaving", "in office") or bool(o and o["current"])
        if status == "departed":
            current = False
        people.append({
            "name": events[-1].person, "current": current,
            "role": (o["role"] if o else None) or events[-1].role, "status": status,
            "leaving_on": leaving.isoformat() if leaving else None,
            "events": [{
                "filing_date": e.filing_date.isoformat() if e.filing_date else None,
                "change": e.change_type, "change_label": CHANGE_LABELS.get(e.change_type),
                "role": e.role, "effective": e.effective, "sentence": describe(e),
                "verified": e.verified, "source_url": e.source_url,
            } for e in reversed(events)],
        })  # fmt: skip
    people.sort(key=lambda p: p["events"][0]["filing_date"] or "", reverse=True)
    departed = {k for k, ev in groups.items() if _status(ev, today)[0] == "departed"}

    current: dict[str, dict | None] = {}
    for role, pattern in ROLES.items():
        pick = None
        appointed = [e for k, ev in groups.items() if k not in departed for e in ev
                     if e.change_type in ARRIVING and pattern.search(e.role or "")]  # fmt: skip
        if appointed:
            e = max(appointed, key=lambda x: (x.filing_date or date.min, x.seq))
            pick = {"name": e.person, "title": e.role,
                    "since": (effective_date(e.effective) or e.filing_date).isoformat()
                    if (e.effective or e.filing_date) else None,
                    "basis": "8-K item 5.02",
                    "filing_date": e.filing_date.isoformat() if e.filing_date else None,
                    "source_url": e.source_url}  # fmt: skip
        holders = [o for o in owners if o["current"] and o.get("kind") == "person"
                   and pattern.search(o.get("officer_title") or o.get("role") or "")
                   and key_from_filed(o["name_as_filed"]) not in departed]  # fmt: skip
        if holders:
            o = max(holders, key=lambda x: x["last_filed"])
            same = pick is not None and key_from_filed(o["name_as_filed"]) == key_from_text(
                pick["name"])  # fmt: skip
            # a Form 4 wins only when someone else took the role after the 8-K appointment
            newer = pick is None or (not same and o["first_filed"] and o["first_filed"].isoformat()
                                     > (pick["filing_date"] or ""))  # fmt: skip
            if newer:
                pick = {"name": o["name"], "title": o.get("officer_title") or o["role"],
                        "since": o["first_filed"].isoformat() if o["first_filed"] else None,
                        "basis": "Form 4 officer title",
                        "filing_date": o["last_filed"].isoformat(),
                        "source_url": filing_index_url(cik, o["last_accession"])}  # fmt: skip
        current[role] = pick
    return {"current_leadership": current, "people": people[:PEOPLE_MAX]}
