"""Executive pay (D-10) and insider trading plans (D-11) from the SEC's ecd taxonomy tags, read
from the Financial Statement and Notes data sets (docs/contracts/executive-pay.md,
docs/contracts/insider-plans.md).

* Pay versus performance (Item 402(v) of Regulation S-K) is tagged in the proxy: the PEO's total
  pay and compensation actually paid (per person when there were two PEOs), the average for the
  other named executives, company and peer TSR, net income and the company-selected measure. The
  Summary Compensation Table itself is not tagged, so there is no per-NEO row.
* Trading arrangements (Item 408(a)) are tagged in 10-Qs and 10-Ks: who adopted or terminated a
  Rule 10b5-1 (or other) plan, when, for how long and for how many shares.

One pass over num.tsv and txt.tsv per monthly data set keeps only these tags. Values are as
tagged: nothing is recomputed. Information, not signals.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from app.services.sec_client import normalize_cik

csv.field_size_limit(50_000_000)

PAY_NUM = {
    "PeoTotalCompAmt": "peo_total_comp",
    "PeoActuallyPaidCompAmt": "peo_cap",
    "NonPeoNeoAvgTotalCompAmt": "neo_avg_total_comp",
    "NonPeoNeoAvgCompActuallyPaidAmt": "neo_avg_cap",
    "TotalShareholderRtnAmt": "tsr",
    "PeerGroupTotalShareholderRtnAmt": "peer_tsr",
    "CoSelectedMeasureAmt": "csm_value",
    "NetIncomeLoss": "net_income",  # us-gaap, kept only from a filing with a PvP table
}
PAY_TXT = {"PeoName": "peo_name", "CoSelectedMeasureName": "csm_name", "MeasureName": "measure"}
PLAN_NUM = {"TrdArrSecuritiesAggAvailAmt": "shares"}
PLAN_TXT = {
    "TrdArrIndName": "name", "TrdArrIndTitle": "title", "TrdArrAdoptionDate": "adopted",
    "TrdArrTerminationDate": "terminated", "TrdArrDuration": "duration",
    "TrdArrExpirationDate": "expiration",
    "Rule10b51ArrAdoptedFlag": "r_adopted", "Rule10b51ArrTrmntdFlag": "r_terminated",
    "NonRule10b51ArrAdoptedFlag": "n_adopted", "NonRule10b51ArrTrmntdFlag": "n_terminated",
}  # fmt: skip
PLAN_FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A", "10-KT", "10-KT/A")
QUARTER_DAYS = 100  # a fiscal quarter and some slack: the window Item 408(a) reports on
PRELIMINARY = ("PRE 14A", "PRER14A", "PRE 14C", "PREM14A", "PREC14A")


def _ymd(value: str | None) -> date | None:
    try:
        return datetime.strptime((value or "").strip()[:8], "%Y%m%d").date()
    except ValueError:
        return None


_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def _month(word: str) -> int | None:
    """1-12 for a month name or its abbreviation ('Sep', 'Sept', 'September'), else None."""
    w = word.lower().rstrip(".")
    for i, name in enumerate(_MONTH_NAMES, 1):
        if len(w) >= 3 and name.startswith(w):
            return i
    return None


_DATE_PATTERNS = (
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?!\d)"), "mdy"),
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s*,?\s*(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\b"), "Mdy"),
    (re.compile(r"\b(\d{1,2})[\s-]*([A-Za-z]{3,9})[\s,-]*(\d{4}|\d{2})\b"), "dMy"),
)


def parse_date(value: str | None) -> date | None:
    """The one date in a tagged text: 'November 24, 2025', 'On May 7, 2024', 'Adoption
    (November 12, 2025)', '6-Sep-23', '9/6/2024(3)', '2025-11-24'. None when the text holds no
    full date ('June 2023', 'Adoption') or two different ones ('September 22, 2025 and
    September 21, 2026'): a doubtful date is worse than none."""
    v = " ".join((value or "").replace("\u00a0", " ").split())
    found: set[date] = set()
    for rx, kind in _DATE_PATTERNS:
        for m in rx.finditer(v):
            a, b, c = m.groups()
            try:
                if kind == "ymd":
                    y, mo, d = int(a), int(b), int(c)
                elif kind == "mdy":
                    mo, d, y = int(a), int(b), int(c)
                elif kind == "Mdy":
                    mo, d, y = _month(a), int(b), int(c)
                else:
                    d, mo, y = int(a), _month(b), int(c)
                if mo is None:
                    continue
                y += 2000 if y < 100 else 0
                found.add(date(y, mo, d))
            except ValueError:
                continue
    return found.pop() if len(found) == 1 else None


def parse_duration_days(value: str | None) -> int | None:
    """ISO 8601 durations as tagged (P403D, P1Y2M, P13M): whole days, years as 365 and months
    as 30 when the tag is not in days. Text ('until all shares are sold') gives None."""
    m = re.fullmatch(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?", (value or "").strip())
    if not m or not any(m.groups()):
        return None
    y, mo, w, d = (int(x) if x else 0 for x in m.groups())
    return y * 365 + mo * 30 + w * 7 + d


def _dims(segments: str) -> dict[str, str]:
    out = {}
    for part in (segments or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _rows(z: zipfile.ZipFile, name: str):
    member = next(n for n in z.namelist() if n.lower().endswith(name))
    with z.open(member) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
        header = text.readline().rstrip("\n").split("\t")
        col = {h: i for i, h in enumerate(header)}
        for line in text:
            yield col, line


def parse_notes_zip(path: str | Path) -> tuple[list[dict], list[dict], dict]:
    """(pay facts, trading-plan rows, stats) from one monthly data set."""
    source = "sec:fsn:" + Path(path).stem
    want = set(PAY_NUM) | set(PAY_TXT) | set(PLAN_NUM) | set(PLAN_TXT)
    with zipfile.ZipFile(path) as z:
        subs = {}
        for col, line in _rows(z, "sub.tsv"):
            f = line.rstrip("\n").split("\t")
            subs[f[col["adsh"]]] = {"cik": f[col["cik"]], "form": f[col["form"]].upper(),
                                    "filed": _ymd(f[col["filed"]]),
                                    "period": _ymd(f[col["period"]])}  # fmt: skip
        raw: list[tuple] = []  # (kind, adsh, tag, ddate, qtrs, dimh, value, unit)
        for kind in ("num", "txt"):
            for col, line in _rows(z, f"{kind}.tsv"):
                parts = line.split("\t", 3)
                if len(parts) < 3 or parts[1] not in want:
                    continue
                f = line.rstrip("\n").split("\t")
                if len(f) < len(col) or f[col["coreg"]]:
                    continue
                version = f[col["version"]]
                if parts[1] == "NetIncomeLoss" and not version.startswith("us-gaap"):
                    continue
                if parts[1] != "NetIncomeLoss" and not version.startswith("ecd"):
                    continue
                raw.append((kind, f[col["adsh"]], parts[1], _ymd(f[col["ddate"]]),
                            f[col["qtrs"]], f[col["dimh"]], f[col["value"]],
                            f[col["uom"]] if kind == "num" else None))  # fmt: skip
        hashes = {r[5] for r in raw}
        dims = {}
        for col, line in _rows(z, "dim.tsv"):
            f = line.rstrip("\n").split("\t")
            if f[0] in hashes:
                dims[f[0]] = f[col["segments"]] if len(f) > col["segments"] else ""
    pay = _pay(raw, dims, subs, source)
    plans = _plans(raw, dims, subs, source)
    stats = {"pay_facts": len(pay), "pay_filings": len({p["accession_number"] for p in pay}),
             "plan_rows": len(plans),
             "plan_filings": len({p["accession_number"] for p in plans})}  # fmt: skip
    return pay, plans, stats


def _pay(raw, dims, subs, source) -> list[dict]:
    pvp = {r[1] for r in raw if r[2] in ("PeoTotalCompAmt", "PeoActuallyPaidCompAmt")}
    out = []
    for kind, adsh, tag, ddate, qtrs, dimh, value, unit in raw:
        if tag not in PAY_NUM and tag not in PAY_TXT:
            continue
        sub = subs.get(adsh)
        if sub is None or adsh not in pvp or sub["form"] in PRELIMINARY or sub["filed"] is None:
            continue
        d = _dims(dims.get(dimh, ""))
        if tag == "NetIncomeLoss" and (d or qtrs != "4"):
            continue  # the PvP column is the year's consolidated net income
        num = None
        if kind == "num":
            try:
                num = float(value)
            except ValueError:
                continue
        out.append({
            "cik": normalize_cik(sub["cik"]), "accession_number": adsh, "form_type": sub["form"],
            "filing_date": sub["filed"], "fiscal_year_end": ddate,
            "field": PAY_NUM.get(tag) or PAY_TXT[tag],
            "category": d.get("ExecutiveCategory"), "member": d.get("Individual"),
            "dims": ";".join(f"{k}={v}" for k, v in sorted(d.items())) or None,
            "value_num": num, "value_text": None if kind == "num" else value.strip()[:500],
            "unit": unit, "source": source,
        })  # fmt: skip
    # one fact per (filing, field, year, dims): a value tagged twice is the same value
    best = {}
    for r in out:
        best[(r["accession_number"], r["field"], r["fiscal_year_end"], r["dims"],
              r["value_text"] if r["field"] == "measure" else None)] = r  # fmt: skip
    return list(best.values())


def _truthy(v: str | None) -> bool | None:
    s = (v or "").strip().lower()
    return True if s in ("true", "1", "yes") else False if s in ("false", "0", "no") else None


def _plan_type(rule: bool | None, non_rule: bool | None) -> str | None:
    if rule and not non_rule:
        return "rule_10b5_1"
    if non_rule and not rule:
        return "non_rule_10b5_1"
    return None


def _plans(raw, dims, subs, source) -> list[dict]:
    groups: dict[tuple[str, str], dict] = {}
    for _kind, adsh, tag, _ddate, _qtrs, dimh, value, _unit in raw:
        if tag not in PLAN_TXT and tag not in PLAN_NUM:
            continue
        sub = subs.get(adsh)
        if sub is None or sub["form"] not in PLAN_FORMS:
            continue
        d = _dims(dims.get(dimh, ""))
        key = ";".join(f"{k}={v}" for k, v in sorted(d.items()))
        groups.setdefault((adsh, key), {"dims": d})[PLAN_TXT.get(tag) or PLAN_NUM[tag]] = (
            value.strip()
        )
    out = []
    for (adsh, key), g in groups.items():
        if not key or not (g.get("adopted") or g.get("terminated")):
            continue  # a filing-wide flag, or a person with no date tagged
        sub = subs[adsh]
        person = g["dims"].get("Individual")
        # the flags sit on the person, on the arrangement or on both
        up = groups.get((adsh, f"Individual={person}"), {}) if person else {}
        flags = {k: _truthy(g.get(k) or up.get(k))
                 for k in ("r_adopted", "r_terminated", "n_adopted", "n_terminated")}  # fmt: skip
        name = g.get("name") or up.get("name")
        title = g.get("title") or up.get("title")
        shares = g.get("shares") or up.get("shares")
        try:
            # a count tagged negative (shown in parentheses as a sale) is still a count
            n_shares = abs(float(shares)) if shares else None
        except ValueError:
            n_shares = None
        adopted, terminated = parse_date(g.get("adopted")), parse_date(g.get("terminated"))
        expiration = parse_date(g.get("expiration"))
        if terminated and sub["filed"] and terminated > sub["filed"]:
            # a "termination" after the filing date is the plan's scheduled end (hand-check
            # 2026-11-24: "The trading plan terminates on September 3, 2024")
            expiration, terminated = expiration or terminated, None
            g = {**g, "terminated": None}
        adopt_flag = flags["r_adopted"] or flags["n_adopted"]
        term_flag = flags["r_terminated"] or flags["n_terminated"]
        # A filing that reports a termination often tags the original adoption date too; that
        # adoption happened in an earlier period, so it is not an adoption in this filing.
        # Item 408(a) covers the last fiscal quarter: an adoption dated well before it was
        # disclosed earlier ("as previously disclosed, ... adopted on June 2, 2025"), even when
        # the adopted flag is set again.
        in_quarter = (
            adopted is None
            or sub["period"] is None
            or (adopted >= sub["period"] - timedelta(days=QUARTER_DAYS))
        )
        emit_adopt = (
            g.get("adopted") is not None
            and in_quarter
            and (adopt_flag or (not term_flag and g.get("terminated") is None))
        )
        emit_term = g.get("terminated") is not None or (term_flag and not adopt_flag)
        base = {
            "cik": normalize_cik(sub["cik"]), "accession_number": adsh,
            "form_type": sub["form"], "filing_date": sub["filed"], "period": sub["period"],
            "member": key[:300], "person_name": " ".join((name or "").split())[:200] or None,
            "title": " ".join((title or "").split())[:300] or None, "source": source,
        }  # fmt: skip
        if emit_adopt:
            out.append({**base, "action": "adopted",
                        "plan_type": _plan_type(flags["r_adopted"], flags["n_adopted"]),
                        "plan_date": adopted,
                        "plan_date_text": None if adopted else g.get("adopted")[:100],
                        "original_adoption_date": None,
                        "duration_days": parse_duration_days(g.get("duration")),
                        "expiration_date": expiration, "shares": n_shares})  # fmt: skip
        if emit_term:
            text = g.get("terminated")
            out.append({**base, "action": "terminated",
                        "plan_type": _plan_type(flags["r_terminated"], flags["n_terminated"]),
                        "plan_date": terminated,
                        "plan_date_text": None if terminated else (text or "")[:100] or None,
                        "original_adoption_date": None if emit_adopt else adopted,
                        "duration_days": None, "expiration_date": None,
                        "shares": None})  # fmt: skip
    return out


# -- load ---------------------------------------------------------------------------------


def load(db, path: str | Path) -> dict:
    """Replace the rows of every filing in one data set (the quarterly and monthly sets
    overlap, so a filing is keyed by its accession number, not by the set)."""
    from sqlalchemy import delete, insert

    from app.db.models import ProxyPayFact, TradingPlan

    pay, plans, stats = parse_notes_zip(path)
    for model, rows in ((ProxyPayFact, pay), (TradingPlan, plans)):
        accs = sorted({r["accession_number"] for r in rows})
        for i in range(0, len(accs), 1000):
            db.execute(delete(model).where(model.accession_number.in_(accs[i : i + 1000])))
        for i in range(0, len(rows), 5000):
            db.execute(insert(model), rows[i : i + 5000])
    db.commit()
    return stats
