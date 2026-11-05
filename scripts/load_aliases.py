"""Fill company_aliases with the former names in the SEC submissions archive (issue #3, step 2).

Ingestion keeps them current from then on; this reads them for companies already loaded, without
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
from sqlalchemy import select

from app.db.models import Company
from app.services.ingestion import parse_former_names, store_aliases


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
            former = parse_former_names(json.loads(archive.read(member)).get("formerNames"))
            store_aliases(db, cik, legal_name, former)
            companies += 1
            names += len(former)
            if companies % 2000 == 0:
                db.commit()
        db.commit()
    finally:
        db.close()
    print(f"{names} former names for {companies} companies in {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
