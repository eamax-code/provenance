"""Q-07: activist stakes (Schedule 13D) per company and across companies (docs/contracts/
activists.md). Information about what the filers reported, not signals. Not investment advice.

A chain is one filer's 13D and its 13D/As about a company, in filing order. A filing joins the
chain of an earlier one when they share the filing agent's filer CIK or a reporting person's CIK
(a 13D/A filed by another member of the same group). An original 13D after an exit starts a new
chain. Each filing's figure is the group's as filed: the largest percent a reporting person
reports (each person's line reports the group's shares it is deemed to own), never a sum.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BeneficialOwner, Company, Schedule13DPurpose
from app.services.beneficial_owners import HOLDER_TYPES
from app.services.thirteenf import class_label

D_FORMS = ("SCHEDULE 13D", "SCHEDULE 13D/A")
G_FORMS = ("SCHEDULE 13G", "SCHEDULE 13G/A")
THRESHOLD = 5
MOVE = 0.1  # percentage points: an amendment moving less is "amended", not increased/decreased
EXCERPT = 600
COVERAGE = {"from": "2024-12-18", "note": "Structured Schedules 13D since December 2024; older "
            "free-text schedules are not read, so a chain starts at its first structured "
            "filing."}  # fmt: skip
DISCLAIMER = "Information, not signals. Not investment advice."
# an amendment's Item 4 that only says it is unchanged carries the earlier statement
_UNCHANGED = re.compile(r"\b(no (material )?changes?|unchanged|not (been )?amended|remains? "
                        r"unchanged)\b", re.I)  # fmt: skip


@dataclass
class Filing13:
    accession_number: str
    form: str
    filed_date: date
    event_date: date | None
    filer_cik: str | None
    source_url: str
    persons: list = field(default_factory=list)  # BeneficialOwner rows, in position order

    @property
    def keys(self) -> set[str]:
        return {k for k in [self.filer_cik, *(p.holder_cik for p in self.persons)] if k}

    @property
    def top(self) -> BeneficialOwner:
        """The reporting person with the group's figure: the largest percent (the filer's own
        line on a tie)."""

        def rank(p):
            return (
                p.percent if p.percent is not None else -1,
                p.holder_cik == self.filer_cik,
                -p.position,
            )

        return max(self.persons, key=rank)

    @property
    def percent(self) -> float | None:
        return _f(self.top.percent)

    @property
    def shares(self) -> float | None:
        return _f(self.top.shares)

    @property
    def main(self) -> BeneficialOwner:
        """The filer: the reporting person whose CIK is the filing agent's, else the top one."""
        return next((p for p in self.persons if self.filer_cik and p.holder_cik == self.filer_cik),
                    self.top)  # fmt: skip


def _below(f: Filing13) -> bool:
    return f.percent is not None and f.percent < THRESHOLD


def _f(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def _filings(db: Session, ciks: list[str], forms: tuple, as_of: date | None) -> dict:
    """{subject: [Filing13 in filing order]}"""
    q = select(BeneficialOwner).where(BeneficialOwner.subject_cik.in_(ciks),
                                      BeneficialOwner.form_type.in_(forms))  # fmt: skip
    if as_of:
        q = q.where(BeneficialOwner.filing_date <= as_of)
    by: dict[tuple, Filing13] = {}
    for r in db.scalars(q.order_by(BeneficialOwner.filing_date, BeneficialOwner.accession_number,
                                   BeneficialOwner.position)):  # fmt: skip
        k = (r.subject_cik, r.accession_number)
        if k not in by:
            by[k] = Filing13(r.accession_number, r.form_type, r.filing_date, r.event_date,
                             r.filer_cik, r.source_url)  # fmt: skip
        by[k].persons.append(r)
    out: dict[str, list[Filing13]] = {}
    for (subject, _), f in by.items():
        out.setdefault(subject, []).append(f)
    return out


def chains(filings: list[Filing13]) -> list[list[Filing13]]:
    """One filer's (or group's) 13D and 13D/As, in filing order."""
    out: list[list[Filing13]] = []
    for f in filings:
        home = None
        for c in reversed(out):
            if f.keys & set().union(*(x.keys for x in c)):
                home = c
                break
        exited = home is not None and _below(home[-1])
        if home is None or (f.form == "SCHEDULE 13D" and exited):
            out.append([f])
        else:
            home.append(f)
    return out


def _excerpt(text: str) -> tuple[str, bool]:
    if len(text) <= EXCERPT:
        return text, False
    head = text[:EXCERPT]
    cut = max(head.rfind(". "), head.rfind("; "))
    if cut >= EXCERPT // 3:
        return head[: cut + 1], True
    return head.rsplit(" ", 1)[0], True


def says_unchanged(text: str | None) -> bool:
    return bool(text) and len(text) <= 400 and bool(_UNCHANGED.search(text))


def _purpose(chain: list[Filing13], purposes: dict) -> dict | None:
    """Item 4 of the latest filing in the chain that states one, quoted as filed, with that
    filing cited (an amendment leaving Item 4 out, or saying it is unchanged, carries it)."""
    for f in reversed(chain):
        p = purposes.get(f.accession_number)
        if p is None or not p.purpose or says_unchanged(p.purpose):
            continue
        excerpt, truncated = _excerpt(p.purpose)
        return {"excerpt": excerpt, "truncated": truncated, "form": f.form,
                "filed_date": f.filed_date.isoformat(), "accession_number": f.accession_number,
                "source_url": f.source_url,
                "carried_forward": f is not chain[-1]}  # fmt: skip
    return None


def _class(purposes: dict, f: Filing13) -> str | None:
    p = purposes.get(f.accession_number)
    return class_label(p.class_title) if p and p.class_title else None


def _switch(chain: list[Filing13], g_filings: list[Filing13]) -> dict | None:
    keys = set().union(*(x.keys for x in chain))
    before = [g for g in g_filings if g.filed_date <= chain[0].filed_date and g.keys & keys
              and g.accession_number != chain[0].accession_number]  # fmt: skip
    if not before:
        return None
    g = before[-1]
    return {"filed_date": g.filed_date.isoformat(), "form": g.form, "percent": g.percent,
            "accession_number": g.accession_number, "source_url": g.source_url}  # fmt: skip


def _entry(f: Filing13, prev: Filing13 | None, purposes: dict) -> dict:
    p = purposes.get(f.accession_number)
    change = chg_sh = None
    if prev is not None:
        if f.percent is not None and prev.percent is not None:
            change = round(f.percent - prev.percent, 4)
        if f.shares is not None and prev.shares is not None:
            chg_sh = f.shares - prev.shares
    return {"form": f.form, "filed_date": f.filed_date.isoformat(),
            "event_date": f.event_date.isoformat() if f.event_date else None,
            "amendment_number": p.amendment_number if p and f.form.endswith("/A") else None,
            "percent": f.percent, "shares": f.shares, "class_label": _class(purposes, f),
            "change_pct_points": change, "change_shares": chg_sh,
            "accession_number": f.accession_number, "source_url": f.source_url}  # fmt: skip


def _kind(i: int, chain: list[Filing13], switched: bool) -> str:
    f = chain[i]
    if _below(f):
        return "exited"
    if i == 0:
        if f.form == "SCHEDULE 13D":
            return "switched" if switched else "new"
        return "amended"  # the chain's first structured filing is an amendment
    prev = chain[i - 1]
    if f.percent is not None and prev.percent is not None:
        if f.percent - prev.percent >= MOVE:
            return "increased"
        if prev.percent - f.percent >= MOVE:
            return "decreased"
    return "amended"


def _purposes(db: Session, accessions: list[str]) -> dict:
    out = {}
    for i in range(0, len(accessions), 5000):
        for p in db.scalars(select(Schedule13DPurpose).where(
                Schedule13DPurpose.accession_number.in_(accessions[i:i + 5000]))):  # fmt: skip
            out[p.accession_number] = p
    return out


def _chain_view(chain: list[Filing13], g_filings: list, purposes: dict) -> dict:
    last, first = chain[-1], chain[0]
    main = first.main  # the chain's filer: whoever filed its first 13D (a group member may amend)
    return {
        "filer": {"name": main.holder_name, "cik": main.holder_cik or first.filer_cik},
        "group": [
            {
                "name": p.holder_name,
                "cik": p.holder_cik,
                "type": p.holder_type,
                "type_label": HOLDER_TYPES.get((p.holder_type or "").split(",")[0].strip()),
            }
            for p in last.persons
        ],  # fmt: skip
        "current": {
            k: v
            for k, v in _entry(last, chain[-2] if len(chain) > 1 else None, purposes).items()
            if k not in ("change_pct_points", "change_shares")
        },  # fmt: skip
        "first_filed": {
            "form": chain[0].form,
            "filed_date": chain[0].filed_date.isoformat(),
            "percent": chain[0].percent,
            "accession_number": chain[0].accession_number,
            "source_url": chain[0].source_url,
        },  # fmt: skip
        "switched_from_13g": _switch(chain, g_filings),
        "purpose": _purpose(chain, purposes),
        "chain": [_entry(f, chain[i - 1] if i else None, purposes) for i, f in enumerate(chain)],
        "status": "exited" if _below(last) else "current",
    }


def for_company(db: Session, cik: str, status: str = "current", as_of: date | None = None) -> dict:
    d = _filings(db, [cik], D_FORMS, as_of).get(cik, [])
    g = _filings(db, [cik], G_FORMS, as_of).get(cik, [])
    purposes = _purposes(db, [f.accession_number for f in d])
    views = [_chain_view(c, g, purposes) for c in chains(d)]
    # current chains by percent, largest first; then exited ones by exit date, latest first
    current = sorted((v for v in views if v["status"] == "current"),
                     key=lambda v: -(v["current"]["percent"] or 0))  # fmt: skip
    exited = sorted((v for v in views if v["status"] == "exited"),
                    key=lambda v: v["current"]["filed_date"], reverse=True)  # fmt: skip
    views = current + (exited if status == "all" else [])
    notes = []
    if not d:
        notes.append("No structured Schedule 13D about this company in the filings read "
                     "(December 2024 on).")  # fmt: skip
    return {"cik": cik, "data": views, "coverage": COVERAGE, "labels": {"disclaimer": DISCLAIMER},
            "notes": notes}  # fmt: skip


KINDS = ("new", "increased", "decreased", "exited", "switched", "all")


def across(
    db: Session,
    since: date,
    until: date,
    kind: str = "new",
    min_percent: float | None = None,
    allowed: set[str] | None = None,
) -> list[dict]:
    """Every 13D or 13D/A filed in the window, newest first, with its kind from its chain."""
    subjects = sorted({s for (s,) in db.execute(
        select(BeneficialOwner.subject_cik).where(BeneficialOwner.form_type.in_(D_FORMS),
                                                  BeneficialOwner.filing_date >= since,
                                                  BeneficialOwner.filing_date <= until)
        .distinct())})  # fmt: skip
    if allowed is not None:
        subjects = [s for s in subjects if s in allowed]
    if not subjects:
        return []
    d_all = _filings(db, subjects, D_FORMS, until)
    g_all = _filings(db, subjects, G_FORMS, until)
    in_window = [f.accession_number for fs in d_all.values() for f in fs
                 if since <= f.filed_date <= until]  # fmt: skip
    purposes = _purposes(db, [f.accession_number for fs in d_all.values() for f in fs])
    names = {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(subjects)))}
    wanted = set(in_window)
    rows = []
    for subject, fs in d_all.items():
        for chain in chains(fs):
            sw = _switch(chain, g_all.get(subject, []))
            for i, f in enumerate(chain):
                if f.accession_number not in wanted:
                    continue
                k = _kind(i, chain, sw is not None)
                if kind == "new" and k not in ("new", "switched"):
                    continue
                if kind not in ("new", "all") and k != kind:
                    continue
                if min_percent is not None and (f.percent is None or f.percent < min_percent):
                    continue
                e = _entry(f, chain[i - 1] if i else None, purposes)
                co = names.get(subject)
                rows.append({
                    "company": {"cik": subject, "name": co.legal_name if co else None,
                                "ticker": co.ticker if co else None},
                    "filer": {"name": f.main.holder_name,
                              "cik": f.main.holder_cik or f.filer_cik},
                    "group_size": len(f.persons), "kind": k,
                    "form": f.form, "filed_date": e["filed_date"], "event_date": e["event_date"],
                    "amendment_number": e["amendment_number"],
                    "percent": f.percent, "shares": f.shares, "class_label": e["class_label"],
                    "change_pct_points": e["change_pct_points"],
                    "switched_from_13g": sw if k == "switched" else None,
                    "purpose": _purpose(chain[:i + 1], purposes),
                    "accession_number": f.accession_number, "source_url": f.source_url,
                })  # fmt: skip
    rows.sort(key=lambda r: (r["filed_date"], r["accession_number"]), reverse=True)
    return rows
