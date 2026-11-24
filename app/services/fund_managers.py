"""Q-02: Form 13F managers (docs/contracts/managers.md): per-security quarter stats, the
thousands-after-2023 check, and the funds activity list, built in a batch after each load
(scripts/build_13f_stats.py); a manager's own portfolio is read per request.

Amendments per manager and quarter follow thirteenf: an original or a RESTATEMENT replaces,
NEW HOLDINGS adds. Changes compare shares, never values. A reviewed split between the two
quarter ends puts the previous shares on the post-split basis; a security whose managers' total
shares moved 1.9x or more (0.55x or less) while their total value moved under 30% is a possible
split: not compared, not ranked. CUSIPs never leave this module's tables.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db.models import (
    Filing13F,
    Holding13F,
    IssuerCusip,
    ThirteenFActivity,
    ThirteenFFilingScale,
    ThirteenFSecurityStat,
)
from app.services import thirteenf

SPLIT_UP, SPLIT_DOWN, SPLIT_VALUE = 1.9, 0.55, 0.30
SCALE_LOW, SCALE_HIGH = 1 / 2000, 1 / 500  # a filing's median price ratio: thousands
STREAM = 50_000


def current_accessions(db: Session, period: date, as_of: date | None = None,
                       filer: str | None = None) -> tuple[dict[str, list], set[str]]:  # fmt: skip
    """({filer: [filing rows in force]}, filers with a holdings filing) for a quarter."""
    q = select(Filing13F.accession_number, Filing13F.filer_cik, Filing13F.filer_name,
               Filing13F.filing_date, Filing13F.form_type, Filing13F.amendment_type,
               Filing13F.confidential_omitted).where(
        Filing13F.report_period == period,
        Filing13F.form_type.in_(thirteenf.HOLDINGS_FORMS))  # fmt: skip
    if as_of:
        q = q.where(Filing13F.filing_date <= as_of)
    if filer:
        q = q.where(Filing13F.filer_cik == filer)
    per: dict[str, list] = defaultdict(list)
    for f in db.execute(q):
        per[f.filer_cik].append(f)
    out: dict[str, list] = {}
    for cik, fs in per.items():
        fs.sort(key=lambda f: (f.filing_date, f.accession_number))
        current: list = []
        for f in fs:
            if f.amendment_type == "NEW HOLDINGS":
                current.append(f)
            else:  # an original or a restatement replaces what was there
                current = [f]
        out[cik] = current
    return out, set(per)


def _stream(db: Session, period: date, order):
    q = (select(Holding13F.accession_number, Holding13F.cusip, Holding13F.filer_cik,
                Holding13F.shares, Holding13F.value_usd)
         .where(Holding13F.report_period == period).order_by(order)
         .execution_options(yield_per=STREAM))  # fmt: skip
    return db.execute(q)


def build_stats(db: Session, period: date, write: bool = True) -> dict:
    """Per-security stats for a quarter, then each filing's thousands check against them."""
    cur, _ = current_accessions(db, period)
    live = {f.accession_number for fs in cur.values() for f in fs}
    stats: list[dict] = []
    group: str | None = None
    per_filer: dict[str, list[float]] = {}

    def close():
        if group is None or not per_filer:
            return
        held = [(s, v) for s, v in per_filer.values() if s > 0]
        if not held:
            return
        prices = [v / s for s, v in held if v > 0]
        stats.append({"cusip": group, "report_period": period, "holders": len(held),
                      "shares": sum(s for s, _ in held), "value_usd": sum(v for _, v in held),
                      "median_price": statistics.median(prices) if prices else None})  # fmt: skip

    for acc, cusip, filer, shares, value in _stream(db, period, Holding13F.cusip):
        if acc not in live:
            continue
        if cusip != group:
            close()
            group, per_filer = cusip, {}
        sv = per_filer.setdefault(filer, [0.0, 0.0])
        sv[0] += float(shares)
        sv[1] += float(value)
    close()
    med = {s["cusip"]: s["median_price"] for s in stats}
    scale: list[dict] = []
    acc_run, ratios = None, []

    def close_filing():
        if acc_run is None:
            return
        r = statistics.median(ratios) if ratios else None
        scale.append({"accession_number": acc_run, "report_period": period, "price_ratio": r,
                      "suspect": r is not None and SCALE_LOW <= r <= SCALE_HIGH})  # fmt: skip

    for acc, cusip, _filer, shares, value in _stream(db, period, Holding13F.accession_number):
        if acc not in live:
            continue
        if acc != acc_run:
            close_filing()
            acc_run, ratios = acc, []
        m = med.get(cusip)
        if m and float(shares) > 0 and float(value) > 0:
            ratios.append(float(value) / float(shares) / m)
    close_filing()
    out = {"quarter": period.isoformat(), "securities": len(stats), "filings": len(scale),
           "value_scale_suspect": sum(s["suspect"] for s in scale)}  # fmt: skip
    if write:
        db.execute(
            delete(ThirteenFSecurityStat).where(ThirteenFSecurityStat.report_period == period)
        )
        db.execute(delete(ThirteenFFilingScale).where(ThirteenFFilingScale.report_period == period))
        for rows, table in ((stats, ThirteenFSecurityStat), (scale, ThirteenFFilingScale)):
            for i in range(0, len(rows), 20_000):
                db.execute(insert(table), rows[i : i + 20_000])
        _bump_stats_version(db)
        db.commit()
    return out


STATS_VERSION_KEY = "thirteenf:stats_version"


def _bump_stats_version(db: Session) -> None:
    from app.db.models import JobState, utcnow

    row = db.get(JobState, STATS_VERSION_KEY)
    now = utcnow()
    if row is None:
        db.add(JobState(name=STATS_VERSION_KEY, value=now.isoformat(), updated_at=now))
    else:
        row.value, row.updated_at = now.isoformat(), now


def keymap(db: Session) -> dict[str, tuple[str, str]]:
    """CUSIP -> (company CIK, class label): securities matched to a company here."""
    return {c: (cik, thirteenf.class_label(t) or "Shares")
            for c, cik, t in db.execute(select(IssuerCusip.cusip, IssuerCusip.cik,
                                               IssuerCusip.class_title))}  # fmt: skip


def split_between(cik: str, prev: date, cur: date) -> tuple[str, float] | None:
    """A reviewed split of the company dated after prev and on or before cur: (ratio, factor).
    A split dated only to a month or a year counts only when the whole span is in the window."""
    from fractions import Fraction

    from app.services.statements import date_span, reviewed_splits

    for (c, ratio), dates in reviewed_splits().items():
        if c != cik:
            continue
        for d in dates:
            if not d:
                continue
            lo, hi = date_span(d)
            if prev < lo and hi <= cur:
                a, b = ratio.split(":")
                return ratio, float(Fraction(int(a), int(b)))
    return None


def possible_split(shares_now: float, shares_prev: float, value_now: float,
                   value_prev: float) -> bool:  # fmt: skip
    if shares_prev <= 0 or value_prev <= 0:
        return False
    rs, rv = shares_now / shares_prev, value_now / value_prev
    return (rs >= SPLIT_UP or rs <= SPLIT_DOWN) and abs(rv - 1) < SPLIT_VALUE


Split = tuple[str, float]


def split_check(cik: str, prev: date, cur: date, shares_now: float, shares_prev: float,
                value_now: float, value_prev: float) -> tuple[Split | None, bool]:  # fmt: skip
    """(the reviewed split to adjust for, possible split). A reviewed split counts only when
    managers' total shares moved by about its factor (within 2x): the list said 1:8 for iPower
    while managers' shares doubled, so adjusting would have read every holder as buying. A
    split the totals do not confirm, and an unreviewed jump, are possible splits: not compared."""
    split = split_between(cik, prev, cur)
    if split is not None:
        observed = shares_now / shares_prev if shares_prev > 0 else None
        if observed is not None and 0.5 <= observed / split[1] <= 2:
            return split, False
        return None, True
    return None, possible_split(shares_now, shares_prev, value_now, value_prev)


def build_activity(db: Session, period: date, write: bool = True) -> dict:
    """Most bought and sold by funds for a quarter against the quarter before."""
    prev = thirteenf.previous_quarter(period)
    keys = keymap(db)
    cur_now, filed_now = current_accessions(db, period)
    cur_prev, filed_prev = current_accessions(db, prev)
    both = filed_now & filed_prev
    shares: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: {"now": {}, "prev": {}})
    value: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for side, per, p in (("now", cur_now, period), ("prev", cur_prev, prev)):
        live = {f.accession_number for fs in per.values() for f in fs}
        for acc, cusip, filer, sh, val in _stream(db, p, Holding13F.cusip):
            k = keys.get(cusip)
            if k is None or acc not in live:
                continue
            d = shares[k][side]
            d[filer] = d.get(filer, 0.0) + float(sh)
            value[k][0 if side == "now" else 1] += float(val)
    rows = []
    for (cik, label), sides in shares.items():
        now, before = sides["now"], sides["prev"]
        split, maybe = split_check(cik, prev, period, sum(now.values()),
                                   sum(before.values()), *value[(cik, label)])  # fmt: skip
        factor = split[1] if split else 1.0
        before = {f: s * factor for f, s in before.items()}
        tot_now, tot_prev = sum(now.values()), sum(before.values())
        new = sum(1 for f, s in now.items() if s > 0 and before.get(f, 0) <= 0)
        added = sum(1 for f, s in now.items() if f in both and before.get(f, 0) > 0
                    and s > before[f] * 1.0000001)  # fmt: skip
        reduced = sum(1 for f, s in now.items() if f in both and 0 < s
                      and before.get(f, 0) > 0 and s < before[f] * 0.9999999)  # fmt: skip
        exited = sum(1 for f, s in before.items() if s > 0 and f in both and now.get(f, 0) <= 0)
        rows.append({"report_period": period, "issuer_cik": cik, "class_label": label,
                     "previous_period": prev, "managers_new": new, "managers_added": added,
                     "managers_reduced": reduced, "managers_exited": exited,
                     "net_managers": new + added - reduced - exited,
                     "holders": sum(1 for s in now.values() if s > 0),
                     "holders_previous": sum(1 for s in before.values() if s > 0),
                     "shares": tot_now, "shares_previous": tot_prev,
                     "split": split[0] if split else None, "possible_split": maybe})  # fmt: skip
    out = {"quarter": period.isoformat(), "previous": prev.isoformat(), "rows": len(rows),
           "reviewed_splits": sum(1 for r in rows if r["split"]),
           "possible_splits": sum(r["possible_split"] for r in rows)}  # fmt: skip
    if write:
        db.execute(delete(ThirteenFActivity).where(ThirteenFActivity.report_period == period))
        for i in range(0, len(rows), 20_000):
            db.execute(insert(ThirteenFActivity), rows[i : i + 20_000])
        _bump_stats_version(db)
        db.commit()
    return out


# -- reads (the endpoints) -----------------------------------------------------------------------

FULL_QUARTER = 5000  # a quarter with this many managers is fully loaded
LAG = "Form 13F holdings are as of the quarter end and are filed up to 45 days after it."
DISCLAIMER = "Information, not signals. Not investment advice."


def coverage(db: Session) -> dict:
    from sqlalchemy import func

    managers = func.count(Filing13F.filer_cik.distinct())
    per = db.execute(select(Filing13F.report_period, managers).group_by(Filing13F.report_period))
    full = sorted(q for q, n in per if n >= FULL_QUARTER)
    return {"first_complete_quarter": full[0] if full else None,
            "last_complete_quarter": full[-1] if full else None}  # fmt: skip


def latest_quarter(db: Session, as_of: date | None = None) -> date | None:
    return thirteenf.complete_quarter(as_of or date.today(), thirteenf.loaded_through(db))


def search(db: Session, q: str, limit: int = 20) -> tuple[list[dict], bool]:
    from sqlalchemy import func

    from app.db.models import Company
    from app.services.sec_client import normalize_cik

    q = " ".join(q.split())
    cond = []
    if q.isdigit():
        cond.append(Filing13F.filer_cik == normalize_cik(q))
    else:
        cond += [Filing13F.filer_name.ilike(f"%{w}%") for w in q.split()]
    latest = (select(Filing13F.filer_cik, func.max(Filing13F.report_period).label("q"))
              .where(*cond, Filing13F.form_type.in_(thirteenf.HOLDINGS_FORMS))
              .group_by(Filing13F.filer_cik).order_by(func.max(Filing13F.report_period).desc(),
                                                       Filing13F.filer_cik)
              .limit(limit + 1))  # fmt: skip
    found = db.execute(latest).all()
    more = len(found) > limit
    out = []
    companies = set(db.scalars(select(Company.cik).where(Company.cik.in_([f[0] for f in found]))))
    for cik, quarter in found[:limit]:
        cur, _ = current_accessions(db, quarter, filer=cik)
        fs = cur.get(cik, [])
        accs = [f.accession_number for f in fs]
        n, v = db.execute(select(func.count(), func.coalesce(func.sum(Holding13F.value_usd), 0))
                          .where(Holding13F.accession_number.in_(accs))).one()  # fmt: skip
        suspect = _suspect(db, accs)
        out.append({"cik": cik, "name": fs[-1].filer_name if fs else cik,
                    "company_cik": cik if cik in companies else None, "latest_quarter": quarter,
                    "positions": n, "value_usd": None if suspect else float(v),
                    "value_scale_suspect": suspect})  # fmt: skip
    out.sort(key=lambda r: -(r["value_usd"] or 0))
    return out, more


def _suspect(db: Session, accs: list[str]) -> bool:
    if not accs:
        return False
    return bool(db.scalar(select(ThirteenFFilingScale.suspect).where(
        ThirteenFFilingScale.accession_number.in_(accs), ThirteenFFilingScale.suspect.is_(True))
        .limit(1)))  # fmt: skip


def _positions(db: Session, accs: list[str]) -> dict[str, dict]:
    """{cusip: {shares, value, title}} for the filings in force (NEW HOLDINGS added)."""
    out: dict[str, dict] = {}
    if not accs:
        return out
    q = select(Holding13F.cusip, Holding13F.shares, Holding13F.value_usd,
               Holding13F.title_of_class).where(Holding13F.accession_number.in_(accs))  # fmt: skip
    for cusip, sh, val, title in db.execute(q):
        p = out.setdefault(cusip, {"shares": 0.0, "value": 0.0, "title": title})
        p["shares"] += float(sh)
        p["value"] += float(val)
    return out


_cik_map: tuple[float, dict[str, str]] | None = None
CIK_MAP_TTL = 600


def _ciks(db: Session) -> dict[str, str]:
    """CUSIP -> company CIK, read once per process every CIK_MAP_TTL seconds (about 60,000
    rows; an IN query per portfolio and quarter made a 5,500-position manager slow)."""
    import time

    global _cik_map
    if _cik_map is None or time.monotonic() - _cik_map[0] > CIK_MAP_TTL:
        _cik_map = (
            time.monotonic(),
            dict(db.execute(select(IssuerCusip.cusip, IssuerCusip.cik)).all()),
        )
    return _cik_map[1]


def reset_cache() -> None:
    global _cik_map
    _cik_map = None
    _views.clear()


_views: dict[tuple, tuple[float, dict, list]] = {}
VIEW_TTL = 600
VIEW_MAX = 64


def cached_view(db: Session, cik: str, quarter: date, as_of: date | None):
    """(portfolio, history) for a manager and quarter, cached per process: a 5,500-position
    manager took about 430 ms a request (R-2, 24 Nov). Keyed on the 13F holdings version every
    load bumps and the stats version the batch bumps; never longer than VIEW_TTL. The caller
    must not change what it gets back."""
    import time

    from app.db.models import JobState

    stats_version = db.scalar(select(JobState.value).where(JobState.name == STATS_VERSION_KEY))
    version = (thirteenf._holdings_version(db), stats_version)
    key = (cik, quarter, as_of, version)
    hit = _views.get(key)
    if hit and time.monotonic() - hit[0] < VIEW_TTL:
        return hit[1], hit[2]
    p = portfolio(db, cik, quarter, as_of)
    h = history(db, cik, as_of) if p is not None else []
    if len(_views) >= VIEW_MAX:
        _views.pop(next(iter(_views)))
    _views[key] = (time.monotonic(), p, h)
    return p, h


def _grouped(db: Session, pos: dict[str, dict], period: date,
             names: bool = True) -> dict[tuple, dict]:  # fmt: skip
    """Positions per (company, class) or, unmatched, per security under its name as filed."""
    from app.db.models import ThirteenFIssuerName

    keys = _ciks(db)
    unmatched = [c for c in pos if c not in keys]
    found = {}
    if names and unmatched:
        q = select(ThirteenFIssuerName.cusip, ThirteenFIssuerName.name).where(
            ThirteenFIssuerName.cusip.in_(unmatched), ThirteenFIssuerName.report_period == period
        )
        found = dict(db.execute(q).all())
    out: dict[tuple, dict] = {}
    for cusip, p in pos.items():
        label = thirteenf.class_label(p["title"]) or "Shares"
        # an unmatched security is one key per CUSIP: its title as filed can change wording
        # between quarters ("GOLD SHS" against "GOLD SHARES"), which read as new plus exited
        k = ("c", keys[cusip], label) if cusip in keys else ("u", cusip, "")
        g = out.setdefault(k, {"shares": 0.0, "value": 0.0, "title": p["title"], "cusips": set(),
                               "name": found.get(cusip), "label": label})  # fmt: skip
        g["shares"] += p["shares"]
        g["value"] += p["value"]
        g["cusips"].add(cusip)
    return out


def portfolio(db: Session, cik: str, quarter: date, as_of: date | None = None) -> dict | None:
    """The manager's positions for a quarter with changes against the quarter before; None
    when the manager filed no holdings for that quarter."""
    from app.db.models import Company, ThirteenFActivity, ThirteenFSecurityStat

    cur, _ = current_accessions(db, quarter, as_of=as_of, filer=cik)
    fs = cur.get(cik)
    if not fs:
        return None
    prev_q = thirteenf.previous_quarter(quarter)
    pcur, _ = current_accessions(db, prev_q, as_of=as_of, filer=cik)
    pfs = pcur.get(cik)
    now = _grouped(db, _positions(db, [f.accession_number for f in fs]), quarter)
    before = (
        _grouped(db, _positions(db, [f.accession_number for f in pfs]), prev_q) if pfs else None
    )
    matched = {k[1] for k in now if k[0] == "c"} | {k[1] for k in (before or {}) if k[0] == "c"}
    companies = {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(matched)))}
    act = {(a.issuer_cik, a.class_label): a for a in db.scalars(select(ThirteenFActivity).where(
        ThirteenFActivity.report_period == quarter,
        ThirteenFActivity.issuer_cik.in_(matched)))} if matched else {}  # fmt: skip
    unmatched = [
        c for k, g in {**now, **(before or {})}.items() if k[0] == "u" for c in g["cusips"]
    ]
    stats = {}
    if unmatched:
        for s in db.scalars(select(ThirteenFSecurityStat).where(
                ThirteenFSecurityStat.cusip.in_(unmatched),
                ThirteenFSecurityStat.report_period.in_((quarter, prev_q)))):  # fmt: skip
            stats[(s.cusip, s.report_period)] = s
    accs = [f.accession_number for f in fs]
    suspect = _suspect(db, accs)
    total = sum(g["value"] for g in now.values())
    notes: list[str] = []
    positions, exited = [], []
    for k, g in now.items():
        change = None
        if before is not None:
            change = _change(k, g, before.get(k), act, stats, quarter, prev_q, notes)
        positions.append({"key": k, "issuer": _issuer(k, g, companies),
                          "class_label": k[2] or g["label"],
                          "title_of_class": g["title"], "shares": g["shares"],
                          "value_usd": round(g["value"], 2),
                          "pct_of_portfolio": None if suspect or not total
                          else round(g["value"] / total * 100, 2), "change": change})  # fmt: skip
    if before is not None:
        for k, g in before.items():
            if k not in now and g["shares"] > 0:
                exited.append({"issuer": _issuer(k, g, companies),
                               "class_label": k[2] or g["label"],
                               "shares_previous": g["shares"],
                               "value_previous_usd": round(g["value"], 2)})  # fmt: skip
    else:
        notes.append(f"No 13F holdings for {prev_q.isoformat()} are stored for this manager, so "
                     "changes and exits are not shown.")  # fmt: skip
    if suspect:
        notes.append("This filing's values look like thousands although it was filed after 2023 "
                     "(about 1/1,000 of other managers' prices for the same securities): they "
                     "are shown as filed, but no total or portfolio share is given.")  # fmt: skip
    m = [p for p in positions if p["key"][0] == "c"]
    ptotal = sum(g["value"] for g in (before or {}).values())
    psuspect = _suspect(db, [f.accession_number for f in pfs]) if pfs else False
    return {
        "manager": {
            "cik": cik,
            "name": fs[-1].filer_name,
            "company_cik": cik
            if db.scalar(select(Company.cik).where(Company.cik == cik))
            else None,
        },  # fmt: skip
        "quarter": quarter,
        "previous_quarter": prev_q,
        "filing": {
            "accession_number": fs[0].accession_number,
            "form": fs[0].form_type,
            "filed_date": fs[0].filing_date,
            "source_url": _url(cik, fs[0].accession_number),
            "amendments": [
                {
                    "accession_number": f.accession_number,
                    "form": f.form_type,
                    "amendment_type": f.amendment_type,
                    "filed_date": f.filing_date,
                    "source_url": _url(cik, f.accession_number),
                }
                for f in fs[1:]
            ],
            "confidential_omitted": any(f.confidential_omitted for f in fs),
            "value_scale_suspect": suspect,
        },  # fmt: skip
        "totals": {
            "value_usd": None if suspect else round(total, 2),
            "positions": len(positions),
            "matched_value_usd": None if suspect else round(sum(p["value_usd"] for p in m), 2),
            "matched_positions": len(m),
            "previous_value_usd": None if before is None or psuspect else round(ptotal, 2),
            "previous_positions": len(before) if before is not None else None,
        },  # fmt: skip
        "positions": positions,
        "exited": exited,
        "notes": sorted(set(notes)),
    }


def _url(cik: str, acc: str) -> str:
    from app.services.sec_client import filing_index_url

    return filing_index_url(cik, acc)


def _issuer(k: tuple, g: dict, companies: dict) -> dict:
    if k[0] == "c":
        from app.services.intel import display_name

        c = companies.get(k[1])
        return {"cik": k[1],
                "name": display_name(c.legal_name, c.ticker, c.registrant_name) if c else None,
                "ticker": c.ticker if c else None}  # fmt: skip
    return {"cik": None, "name": g.get("name"), "ticker": None}


def _change(k, g, b, act, stats, quarter, prev_q, notes) -> dict | None:
    """new / added / reduced / unchanged on shares; split-adjusted for a confirmed reviewed
    split; None for a possible split."""
    if k[0] == "c":
        a = act.get((k[1], k[2]))
        split = (a.split, None) if a is not None and a.split else None
        maybe = a is not None and a.possible_split
    else:
        split = None
        sn = [stats.get((c, quarter)) for c in g["cusips"]]
        sp = [stats.get((c, prev_q)) for c in g["cusips"]]
        maybe = all(sn) and all(sp) and possible_split(
            sum(s.shares for s in sn), sum(s.shares for s in sp),
            sum(s.value_usd for s in sn), sum(s.value_usd for s in sp))  # fmt: skip
    if maybe:
        notes.append("Possible stock split between the quarters: those changes are not compared.")
        return None
    if b is None:
        return {"status": "new", "shares_previous": 0, "shares_change": g["shares"],
                "shares_change_pct": None, "split_adjusted": False, "split": None}  # fmt: skip
    factor = 1.0
    if split:
        from fractions import Fraction

        x, y = split[0].split(":")
        factor = float(Fraction(int(x), int(y)))
        notes.append(f"Shares before a reviewed {split[0]} split are put on the post-split basis "
                     "before comparing.")  # fmt: skip
    prev = b["shares"] * factor
    diff = g["shares"] - prev
    status = (
        "unchanged" if abs(diff) <= 1e-7 * max(prev, 1) else ("added" if diff > 0 else "reduced")
    )
    return {"status": status, "shares_previous": prev, "shares_change": diff,
            "shares_change_pct": round(diff / prev * 100, 2) if prev else None,
            "split_adjusted": bool(split), "split": split[0] if split else None}  # fmt: skip


def history(db: Session, cik: str, as_of: date | None = None) -> list[dict]:
    """Every loaded quarter for the manager, newest first, after amendments."""

    qs = sorted(set(db.scalars(select(Filing13F.report_period).where(
        Filing13F.filer_cik == cik, Filing13F.form_type.in_(thirteenf.HOLDINGS_FORMS)))),
        reverse=True)  # fmt: skip
    out = []
    for q in qs:
        cur, _ = current_accessions(db, q, as_of=as_of, filer=cik)
        fs = cur.get(cik)
        if not fs:
            continue
        accs = [f.accession_number for f in fs]
        groups = _grouped(db, _positions(db, accs), q, names=False)  # as the portfolio counts
        v = sum(g["value"] for g in groups.values())
        suspect = _suspect(db, accs)
        out.append({"quarter": q, "value_usd": None if suspect else round(v, 2),
                    "positions": len(groups),
                    "value_scale_suspect": suspect,
                    "filing": {"accession_number": fs[0].accession_number,
                               "filed_date": fs[0].filing_date,
                               "source_url": _url(cik, fs[0].accession_number)}})  # fmt: skip
    return out


STRUCTURAL = 2.0  # managers' total shares x2 or /2 in a quarter: not buying or selling


def structural(r) -> bool:
    """Managers' total shares more than doubled or fell by more than half: a merger, takeover,
    listing, reorganisation or CUSIP change, not funds buying or selling (Exxon Mobil's new
    holding company read as 3,916 managers buying and the old one as 3,624 selling)."""
    if r.shares_previous <= 0 or r.shares <= 0:
        return True
    ratio = r.shares / r.shares_previous
    return ratio >= STRUCTURAL or ratio <= 1 / STRUCTURAL


def activity(db: Session, quarter: date, direction: str, min_holders: int, limit: int,
             allowed: set[str] | None = None) -> tuple[list[dict], list[dict]]:  # fmt: skip
    """The ranked list, and the companies left out (possible splits, and managers' shares
    doubled or halved), largest holder counts first."""
    from app.db.models import Company, ThirteenFActivity

    rows = list(db.scalars(select(ThirteenFActivity).where(
        ThirteenFActivity.report_period == quarter)))  # fmt: skip
    out_rows = sorted((r for r in rows if r.possible_split or structural(r)),
                      key=lambda r: -max(r.holders, r.holders_previous))  # fmt: skip
    rows = [r for r in rows if not r.possible_split and not structural(r)
            and max(r.holders, r.holders_previous) >= min_holders
            and (allowed is None or r.issuer_cik in allowed)]  # fmt: skip

    def pct(r):
        return (r.shares - r.shares_previous) / r.shares_previous * 100 if r.shares_previous else 0

    sign = -1 if direction == "bought" else 1
    rows.sort(key=lambda r: (sign * r.net_managers, sign * pct(r), r.issuer_cik, r.class_label))
    rows = rows[:limit]
    from app.services.intel import display_name

    names = {c.cik: c for c in db.scalars(select(Company).where(
        Company.cik.in_([r.issuer_cik for r in rows])))}  # fmt: skip
    left = []
    lnames = {c.cik: c for c in db.scalars(select(Company).where(
        Company.cik.in_([r.issuer_cik for r in out_rows[:5]])))}  # fmt: skip
    for r in out_rows:
        c = lnames.get(r.issuer_cik)
        why = ("possible stock split" if r.possible_split else
               "no longer held" if r.shares <= 0 else
               "first widely held" if r.shares_previous <= 0 or r.holders_previous < 5 else
               "shares doubled" if r.shares > r.shares_previous else "shares halved")  # fmt: skip
        left.append({"name": display_name(c.legal_name, c.ticker, c.registrant_name) if c
                     else r.issuer_cik, "reason": why})  # fmt: skip
    out = []
    for r in rows:
        c = names.get(r.issuer_cik)
        out.append({"issuer": {"cik": r.issuer_cik,
                               "name": display_name(c.legal_name, c.ticker, c.registrant_name)
                               if c else None, "ticker": c.ticker if c else None},
                    "class_label": r.class_label, "managers_new": r.managers_new,
                    "managers_added": r.managers_added, "managers_reduced": r.managers_reduced,
                    "managers_exited": r.managers_exited, "net_managers": r.net_managers,
                    "holders": r.holders, "holders_previous": r.holders_previous,
                    "shares": r.shares, "shares_previous": r.shares_previous,
                    "shares_change_pct": round(pct(r), 2) if r.shares_previous else None,
                    "split_adjusted": bool(r.split), "split": r.split})  # fmt: skip
    return out, left
