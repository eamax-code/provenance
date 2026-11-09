"""Fill former names (company_aliases, issue #3) and company metadata (address, phone, filer
category, EIN, LEI, tickers; issue #9) from the SEC submissions archive.

Ingestion keeps both current from then on; this reads them for companies already loaded, without
any SEC request.

python scripts/load_aliases.py                        # archive in SEC_BULK_DIR
python scripts/load_aliases.py --submissions ~/Downloads/submissions.zip
"""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import select, update

from app.db.models import Company
from app.services.ingestion import parse_former_names, parse_metadata, store_aliases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--submissions", type=Path, default=None)
    args = parser.parse_args()
    settings, Session = bootstrap()
    path = args.submissions or Path(settings.sec_bulk_dir) / "submissions.zip"
    archive = zipfile.ZipFile(path.expanduser())
    members = set(archive.namelist())
    db = Session()
    started, companies, names = time.perf_counter(), 0, 0
    try:
        for cik, legal_name in db.execute(select(Company.cik, Company.legal_name)).all():
            member = f"CIK{cik}.json"
            if member not in members:
                continue
            payload = json.loads(archive.read(member))
            former = parse_former_names(payload.get("formerNames"))
            store_aliases(db, cik, legal_name, former)
            db.execute(update(Company).where(Company.cik == cik).values(**parse_metadata(payload)))
            companies += 1
            names += len(former)
            if companies % 2000 == 0:
                db.commit()
        db.commit()
    finally:
        db.close()
    took = time.perf_counter() - started
    print(f"metadata and {names} former names for {companies} companies in {took:.0f}s")


if __name__ == "__main__":
    main()
