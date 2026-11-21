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
STARTS_ROLE = ARRIVING + ("role_change",)  # a role change also starts the new role
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


_NICK_GROUPS = (
    "timothy tim", "william bill will billy", "robert bob rob bobby", "james jim jimmy jamie",
    "michael mike mick", "thomas tom tommy", "david dave", "daniel dan danny",
    "christopher chris", "jeffrey jeff geoffrey", "benjamin ben", "arthur art", "steven steve",
    "stephen steve", "edward ed eddie ted", "joseph joe joey", "samuel sam", "matthew matt",
    "andrew andy drew", "nicholas nick", "anthony tony", "patrick pat", "richard rick rich dick",
    "kenneth ken kenny", "lawrence larry", "elizabeth liz beth betsy", "katherine kate kathy",
    "catherine cathy kate", "jennifer jen jenny", "susan sue", "margaret meg maggie peggy",
    "alexander alex", "alexandra alex", "gregory greg", "jonathan jon", "john jack",
    "charles charlie chuck", "frederick fred", "raymond ray", "ronald ron", "donald don",
    "douglas doug", "gerald jerry", "kimberly kim", "deborah deb debbie", "rebecca becky",
    "victoria vicki", "theodore ted", "philip phil", "bradford brad", "bradley brad",
)  # fmt: skip
NICKNAMES = {n: g.split()[0] for g in _NICK_GROUPS for n in g.split()}


def _tokens(name: str) -> list[str]:
    words = re.sub(r"[^A-Za-z\s\-']", " ", name or "").lower().split()
    return [w for w in words if w not in _SUFFIX and len(w) > 0]


def _parts_filed(name: str) -> tuple[str, str] | None:
    t = _tokens(name)
    return (t[0], t[1]) if len(t) >= 2 else None  # "COOK TIMOTHY D": last name first


def _parts_text(name: str | None) -> tuple[str, str] | None:
    t = _tokens(name or "")
    return (t[-1], t[0]) if len(t) >= 2 else None  # "Timothy D. Cook": first name first


def key_from_filed(name_as_filed: str) -> tuple[str, str] | None:
    """Forms 3/4: "COOK TIMOTHY D" -> ("cook", "t")."""
    p = _parts_filed(name_as_filed)
    return (p[0], p[1][0]) if p else None


def key_from_text(name: str | None) -> tuple[str, str] | None:
    """8-K text: "Tim Cook" -> ("cook", "t")."""
    p = _parts_text(name)
    return (p[0], p[1][0]) if p else None


def match_people(owner_name_as_filed: str, person: str | None) -> tuple[str, str] | None:
    """How a Form 4 reporting owner and an 8-K person are the same: (method, confidence), or
    None. Same last name and first name -> name_exact/high; a known nickname (Tim, Timothy)
    -> name_nickname/high; the same first initial only -> name_initial/medium."""
    a, b = _parts_filed(owner_name_as_filed), _parts_text(person)
    if not a or not b or a[0] != b[0]:
        return None
    if a[1] == b[1]:
        return "name_exact", "high"
    if NICKNAMES.get(a[1], a[1]) == NICKNAMES.get(b[1], b[1]):
        return "name_nickname", "high"
    if a[1][0] == b[1][0] and (len(a[1]) == 1 or len(b[1]) == 1):
        return "name_initial", "medium"
    return None


_NEW_ROLE = re.compile(r"(?:\bto\b|\bbecomes?\b|\bnamed\b|\bas\b)\s+(?:the\s+)?(.+)$", re.I)


def new_role(e: OfficerChange) -> str:
    """The role a change starts. For a role change the record's `role` is the role being left
    ("transitions from Chief Executive Officer to Executive Chair"), so read `what`."""
    if e.change_type != "role_change":
        return e.role or ""
    m = _NEW_ROLE.search(e.what or "")
    return m.group(1) if m else ""


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
    owner_list = [o for o in owners if o.get("kind") == "person"]
    groups: dict[tuple, list[OfficerChange]] = {}
    for c in changes(db, cik, as_of):
        k = key_from_text(c.person)
        if k:
            groups.setdefault(k, []).append(c)
    people = []
    owner_for: dict[tuple, dict] = {}
    for k, events in groups.items():
        status, leaving, ev = _status(events, today)
        found = [(o, m) for o in owner_list if (m := match_people(o["name_as_filed"],
                                                                 events[-1].person))]  # fmt: skip
        o, match = found[0] if len(found) == 1 else (None, None)  # ambiguous stays unmatched
        if o is not None:
            owner_for[k] = o
        current = status in ("appointed", "leaving", "in office") or bool(o and o["current"])
        if status == "departed":
            current = False
        spelled = sorted({e.person for e in events if e.person})
        people.append({
            "name": o["name"] if o else events[-1].person,
            "aliases": [n for n in spelled if not o or n != o["name"]],
            "match": {"method": match[0], "confidence": match[1],
                      "reporting_owner_cik": o["owner_cik"]} if o else None,
            "current": current,
            "role": (o["role"] if o else None) or events[-1].role, "status": status,
            "reporting_since": o["first_filed"].isoformat() if o and o["first_filed"] else None,
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
        appointed = [(k, e) for k, ev in groups.items() if k not in departed for e in ev
                     if e.change_type in STARTS_ROLE and pattern.search(new_role(e))]  # fmt: skip
        # people who moved out of this role by a role change that has taken effect
        left = {
            k for k, ev in groups.items() for e in ev
            if e.change_type == "role_change" and pattern.search(e.role or "")
            and not pattern.search(new_role(e))
            and (effective_date(e.effective) or e.filing_date or date.min) <= today
        }  # fmt: skip
        if appointed:
            k, e = max(appointed, key=lambda x: (x[1].filing_date or date.min, x[1].seq))
            o = owner_for.get(k)
            pick = {"name": o["name"] if o else e.person, "title": new_role(e),
                    "since": (effective_date(e.effective) or e.filing_date).isoformat()
                    if (e.effective or e.filing_date) else None,
                    "basis": "8-K item 5.02",
                    "reporting_since": o["first_filed"].isoformat()
                    if o and o["first_filed"] else None,
                    "filing_date": e.filing_date.isoformat() if e.filing_date else None,
                    "source_url": e.source_url}  # fmt: skip
        moved = {id(owner_for[k]) for k in left if k in owner_for}
        holders = [o for o in owners if o["current"] and o.get("kind") == "person"
                   and pattern.search(o.get("officer_title") or o.get("role") or "")
                   and key_from_filed(o["name_as_filed"]) not in departed
                   and id(o) not in moved]  # fmt: skip
        if holders:
            o = max(holders, key=lambda x: x["last_filed"])
            same = pick is not None and (
                pick["name"] == o["name"] or match_people(o["name_as_filed"], pick["name"])
            )
            # a Form 4 wins only when someone else took the role after the 8-K appointment
            newer = pick is None or (not same and o["first_filed"] and o["first_filed"].isoformat()
                                     > (pick["filing_date"] or ""))  # fmt: skip
            if newer:
                pick = {"name": o["name"], "title": o.get("officer_title") or o["role"],
                        "since": None,  # Form 4 says only since when the person reports
                        "reporting_since": o["first_filed"].isoformat()
                        if o["first_filed"] else None,
                        "basis": "Form 4 officer title",
                        "filing_date": o["last_filed"].isoformat(),
                        "source_url": filing_index_url(cik, o["last_accession"])}  # fmt: skip
        current[role] = pick
    return {"current_leadership": current, "people": people[:PEOPLE_MAX]}
