"""A company's connections as one graph (ADR 0011): its insiders (Forms 3, 4, 5), the other
companies those insiders report on (board interlocks), its subsidiaries (exhibit 21) and its
holders of more than 5% (Schedules 13D and 13G).

Every edge carries the filing it comes from. Nodes that are companies in this database carry
their CIK so a client can open them. `as_of` uses only filings made by that date.
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, GraphSourceState
from app.services import beneficial_owners, insiders, leadership, subsidiaries
from app.services.sec_client import filing_index_url, normalize_cik

LAYERS = ("insiders", "interlocks", "subsidiaries", "holders")
MAX_SUBSIDIARIES = 400
MAX_INTERLOCKS_PER_OWNER = 25


def _names(db: Session, ciks: set[str]) -> dict[str, Company]:
    out: dict[str, Company] = {}
    ciks_list = sorted(c for c in ciks if c)
    for i in range(0, len(ciks_list), 500):
        for c in db.scalars(select(Company).where(Company.cik.in_(ciks_list[i : i + 500]))):
            out[c.cik] = c
    return out


def _norm(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    n = re.sub(r"\b(the|inc|corp|corporation|co|company|ltd|limited|llc|plc|lp)\b", " ", n)
    return " ".join(n.split())


def _companies_named(db: Session, names: list[str]) -> dict[str, Company]:
    """Subsidiaries that are themselves SEC registrants, matched on the exact legal name."""
    wanted = {n.upper().rstrip("."): n for n in names}
    out: dict[str, Company] = {}
    keys = sorted(wanted)
    for i in range(0, len(keys), 500):
        chunk = keys[i : i + 500]
        stmt = select(Company).where(func.upper(Company.legal_name).in_(chunk))
        for c in db.scalars(stmt):
            out[wanted[c.legal_name.upper().rstrip(".")]] = c
    return out


def _filing(cik: str, acc: str, form: str, filed: date | None, url: str | None = None) -> dict:
    return {
        "form_type": form,
        "accession_number": acc,
        "filing_date": filed,
        "source_url": url or filing_index_url(cik, acc),
    }


def coverage(db: Session, cik: str) -> dict:
    states = db.scalars(select(GraphSourceState).where(GraphSourceState.cik == cik)).all()
    out = {s.kind: {"checked_at": s.checked_at, "status": s.status} for s in states}
    out["insider_datasets_through"] = insiders.dataset_coverage(db)
    return out


def build(
    db: Session,
    cik: str,
    as_of: date | None = None,
    layers: tuple[str, ...] = LAYERS,
    former: bool = False,
) -> dict:
    cik = normalize_cik(cik)
    center = db.scalar(select(Company).where(Company.cik == cik))
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    sources: dict[str, dict] = {}

    def company_node(c_cik: str, label: str, group: str, **detail) -> str:
        nid = f"company:{c_cik}"
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": "company", "label": label, "cik": c_cik,
                          "group": group, "detail": detail}  # fmt: skip
        return nid

    company_node(cik, center.legal_name if center else f"CIK {cik}", "center",
                 ticker=center.ticker if center else None)  # fmt: skip

    owners: list[dict] = []
    if "insiders" in layers or "interlocks" in layers:
        owners = insiders.roles(db, cik, as_of)
        leadership.apply_to_roles(db, cik, owners, as_of)  # an 8-K departure ends a role (K-02)
        if not former:
            owners = [o for o in owners if o["current"]]
        insiders.activity(db, cik, owners, as_of)
    known = _names(db, {o["owner_cik"] for o in owners})

    if "insiders" in layers:
        for o in owners:
            comp = known.get(o["owner_cik"])
            if comp is not None:
                nid = company_node(o["owner_cik"], comp.legal_name, "insiders")
            else:
                nid = f"{o['kind']}:{o['owner_cik']}"
                nodes[nid] = {
                    "id": nid,
                    "type": o["kind"],
                    "label": o["name"],
                    "cik": None,
                    "group": "insiders",
                    "detail": {
                        "name_as_filed": o["name_as_filed"],
                        "reporting_owner_cik": o["owner_cik"],
                        "shares_held": o["shares_held"],
                        "open_market_12m": o["open_market_12m"],
                    },
                }
            kind = (
                "officer" if o["is_officer"]
                else "director" if o["is_director"]
                else "ten_percent_owner" if o["is_ten_percent_owner"]
                else "other_insider"
            )  # fmt: skip
            edges.append(
                {
                    "source": nid,
                    "target": f"company:{cik}",
                    "type": kind,
                    "label": o["role"],
                    "current": o["current"],
                    "ended": o.get("ended"),
                    "leaving_on": o.get("leaving_on"),
                    "since": o["first_filed"],
                    "last": o["last_filed"],
                    "filings": o["filings"],
                    "evidence": _filing(cik, o["last_accession"], o["last_form"], o["last_filed"]),
                }
            )
        sources["insiders"] = {
            "count": len(owners),
            "current": sum(1 for o in owners if o["current"]),
            "through": insiders.dataset_coverage(db),
            "note": "Forms 3, 4 and 5. An insider is former after an 8-K item 5.02 departure, or "
            "after two years without a filing.",
        }

    if "interlocks" in layers and owners:
        people = [o for o in owners if o["is_director"] or o["is_officer"]]
        other = insiders.other_roles(db, [o["owner_cik"] for o in people], cik, as_of)
        issuer_names = _names(db, {i["issuer_cik"] for v in other.values() for i in v})
        count = 0
        for o in people:
            src = (
                f"company:{o['owner_cik']}" if o["owner_cik"] in known
                else f"{o['kind']}:{o['owner_cik']}"
            )  # fmt: skip
            if src not in nodes:
                continue
            roles = sorted(other.get(o["owner_cik"], []), key=lambda r: r["last_filed"],
                           reverse=True)  # fmt: skip
            for r in roles[:MAX_INTERLOCKS_PER_OWNER]:
                if not former and not r["current"]:
                    continue
                comp = issuer_names.get(r["issuer_cik"])
                tid = company_node(
                    r["issuer_cik"], comp.legal_name if comp else f"CIK {r['issuer_cik']}",
                    "interlocks", ticker=comp.ticker if comp else None,
                )  # fmt: skip
                edges.append(
                    {
                        "source": src,
                        "target": tid,
                        "type": "interlock",
                        "label": r["role"],
                        "current": r["current"],
                        "since": None,
                        "last": r["last_filed"],
                        "filings": None,
                        "evidence": _filing(
                            r["issuer_cik"], r["last_accession"], "4", r["last_filed"]
                        ),  # fmt: skip
                    }
                )
                count += 1
        sources["interlocks"] = {
            "count": count,
            "companies": sum(1 for n in nodes.values() if n["group"] == "interlocks"),
            "note": "Other companies where this company's directors and officers file Forms 3,"
            " 4 or 5.",
        }

    if "holders" in layers:
        hs = beneficial_owners.holders(db, cik, as_of, below=former)
        known_h = _names(db, {h["cik"] for h in hs if h["cik"]})
        for h in hs:
            comp = known_h.get(h["cik"] or "")
            same = [f"{k}:{h['cik']}" for k in ("person", "entity")] if h["cik"] else []
            existing = next((i for i in same if i in nodes), None)  # also an insider
            if comp is not None:
                nid = company_node(h["cik"], comp.legal_name, "holders")
            elif existing:
                nid = existing
            else:
                nid = f"holder:{h['cik'] or _norm(h['name'])}"
                nodes.setdefault(
                    nid,
                    {"id": nid, "type": "person" if h["holder_type"] == "IN" else "organization",
                     "label": h["name"], "cik": None, "group": "holders",
                     "detail": {"holder_type": h["holder_type_label"], "group": h["group"]}},
                )  # fmt: skip
            pct = f"{h['percent']:g}%" if h["percent"] is not None else "stake not stated"
            edges.append(
                {
                    "source": nid,
                    "target": f"company:{cik}",
                    "type": "holder",
                    "label": f"{pct} (Schedule {h['schedule']})",
                    "current": not h["below_threshold"],
                    "since": None,
                    "last": h["filing_date"],
                    "filings": None,
                    "percent": h["percent"],
                    "shares": h["shares"],
                    "evidence": _filing(
                        cik,
                        h["accession_number"],
                        h["form_type"],
                        h["filing_date"],
                        h["source_url"],
                    ),  # fmt: skip
                }
            )
        sources["holders"] = {
            "count": len(hs),
            "note": "Schedules 13D and 13G filed as structured data (December 2024 on).",
        }

    if "subsidiaries" in layers:
        lst = subsidiaries.latest(db, cik, as_of)
        if lst:
            rows = lst["rows"]
            matched = _companies_named(db, [r.name for r in rows[:MAX_SUBSIDIARIES]])
            added = {_norm(n) for n in lst["added"]}
            ev = _filing(cik, lst["accession_number"], lst["form_type"], lst["filing_date"],
                         lst["source_url"])  # fmt: skip
            for r in rows[:MAX_SUBSIDIARIES]:
                comp = matched.get(r.name)
                if comp is not None and comp.cik != cik:
                    nid = company_node(comp.cik, comp.legal_name, "subsidiaries",
                                       jurisdiction=r.jurisdiction)  # fmt: skip
                    nodes[nid]["detail"].update(
                        jurisdiction=r.jurisdiction,
                        jurisdiction_group=subsidiaries.jurisdiction_group(r.jurisdiction),
                    )
                else:
                    nid = f"subsidiary:{cik}:{r.position}"
                    nodes[nid] = {
                        "id": nid,
                        "type": "subsidiary",
                        "label": r.name,
                        "cik": None,
                        "group": "subsidiaries",
                        "detail": {
                            "jurisdiction": r.jurisdiction,
                            "jurisdiction_group": subsidiaries.jurisdiction_group(r.jurisdiction),
                        },
                    }
                nodes[nid]["detail"]["new_this_year"] = (
                    lst["previous"] is not None and _norm(r.name) in added
                )
                edges.append(
                    {
                        "source": f"company:{cik}",
                        "target": nid,
                        "type": "subsidiary",
                        "label": r.jurisdiction or "Jurisdiction not stated",
                        "current": True,
                        "since": None,
                        "last": lst["filing_date"],
                        "filings": None,
                        "evidence": ev,
                    }
                )
            sources["subsidiaries"] = {
                "count": len(rows),
                "shown": min(len(rows), MAX_SUBSIDIARIES),
                "exhibit": lst["exhibit"],
                "filing": ev,
                "previous": lst["previous"],
                "added": lst["added"][:100],
                "removed": lst["removed"][:100],
                "note": "Exhibit 21 lists significant subsidiaries; companies may omit those"
                " that are not significant.",
            }
        else:
            sources["subsidiaries"] = {"count": 0, "note": "No exhibit 21 read yet."}

    return {
        "company": {
            "cik": cik,
            "name": center.legal_name if center else None,
            "ticker": center.ticker if center else None,
        },  # fmt: skip
        "as_of": as_of,
        "nodes": list(nodes.values()),
        "edges": edges,
        "sources": sources,
        "coverage": coverage(db, cik),
    }
