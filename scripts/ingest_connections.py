#!/usr/bin/env python
"""Load the sources of the connections graph (ADR 0011).

  python scripts/ingest_connections.py --insider-quarters 12      # latest 12 quarterly data sets
  python scripts/ingest_connections.py --quarter 2025q3            # one data set
  python scripts/ingest_connections.py --showcase                  # exhibit 21, 13D/G, recent 3/4/5
  python scripts/ingest_connections.py --cik 320193 --cik 789019
  python scripts/ingest_connections.py --active --kinds subsidiaries,holders   # E-5, resumable

The insider data sets (every Form 3, 4 and 5 of a quarter, about 8 MB each) are downloaded into
SEC_BULK_DIR/insiders and loaded for all issuers; a quarter already loaded with the same file is
skipped. Per-company sources are read from EDGAR (needs SEC_USER_AGENT); the API also reads them
on demand for keyed callers, never for the demo key.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import bootstrap

from app.api.routes_graph import refresh_sources
from app.services import insiders
from app.services.public import showcase_ciks
from app.services.sec_client import SecClient, normalize_cik


def active_largest_first(db, kinds) -> list[str]:
    """Active reporters (an annual report in two years), USD reporters by latest revenue first,
    then the rest; companies whose sources were all checked in the last 7 days are left out."""
    from datetime import date, timedelta

    from sqlalchemy import case, select

    from app.db.models import GraphSourceState, MartCompany, utcnow

    rows = db.execute(
        select(MartCompany.cik).where(
            MartCompany.latest_annual_report_date >= date.today() - timedelta(days=730))
        .order_by(case((MartCompany.reporting_currency == "USD", 0), else_=1),
                  MartCompany.latest_revenue.desc().nulls_last())
    ).scalars().all()  # fmt: skip
    wanted = set(kinds or ("subsidiaries", "holders", "insiders"))
    recent = utcnow() - timedelta(days=7)
    fresh: dict[str, set] = {}
    for cik, kind in db.execute(select(GraphSourceState.cik, GraphSourceState.kind)
                                .where(GraphSourceState.checked_at >= recent)):  # fmt: skip
        fresh.setdefault(cik, set()).add(kind)
    return [c for c in rows if not wanted <= fresh.get(c, set())]


def save_progress(db, value: dict) -> None:
    from app.db.models import JobState, utcnow

    row = db.get(JobState, "e5:connections")
    text = json.dumps({**value, "at": utcnow().isoformat()})
    if row is None:
        db.add(JobState(name="e5:connections", value=text, updated_at=utcnow()))
    else:
        row.value, row.updated_at = text, utcnow()
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--insider-quarters", type=int, default=0, help="Latest N data sets")
    parser.add_argument("--quarter", action="append", default=[], help="e.g. 2025q3")
    parser.add_argument("--cik", action="append", default=[])
    parser.add_argument("--showcase", action="store_true", help="The public showcase companies")
    parser.add_argument(
        "--active",
        action="store_true",
        help="E-5: active reporters, USD reporters by revenue first; companies "
        "checked in the last 7 days are skipped (resumable)",
    )
    parser.add_argument(
        "--kinds",
        default=None,
        help="Comma-separated: subsidiaries, holders, insiders (default all)",
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    sec = SecClient(settings)
    out: dict = {"datasets": [], "companies": []}
    try:
        if args.insider_quarters or args.quarter:
            available = insiders.discover_datasets(sec)
            wanted = list(available)[-args.insider_quarters :] if args.insider_quarters else []
            wanted += [q for q in args.quarter if q in available and q not in wanted]
            folder = Path(settings.sec_bulk_dir) / "insiders"
            folder.mkdir(parents=True, exist_ok=True)
            for q in wanted:
                dest = folder / f"{q}_form345.zip"
                sec.download_file(available[q], dest)
                out["datasets"].append(insiders.load_dataset(db, dest, q))
                print(json.dumps(out["datasets"][-1], default=str), flush=True)
        ciks = [normalize_cik(c) for c in args.cik]
        if args.showcase:
            ciks += [c for c in showcase_ciks(db, settings)[0] if c not in ciks]
        kinds = tuple(k.strip() for k in args.kinds.split(",")) if args.kinds else None
        if args.active:
            ciks += [c for c in active_largest_first(db, kinds) if c not in ciks]
        if args.limit:
            ciks = ciks[: args.limit]
        done = 0
        for cik in ciks:
            res = refresh_sources(db, sec, cik, kinds)
            done += 1
            if args.active:
                if done % 50 == 0:
                    save_progress(db, {"done": done, "of": len(ciks)})
            else:
                out["companies"].append(res)
                print(json.dumps(res, default=str), flush=True)
        if args.active:
            save_progress(db, {"done": done, "of": len(ciks), "finished": True})
            out["companies"] = done
    finally:
        sec.close()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
