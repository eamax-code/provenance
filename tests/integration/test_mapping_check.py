"""check_mapping: old-mapping rows pass only as reviewed exceptions
(app/data/mapping_exceptions.csv)."""

from __future__ import annotations

import uuid
from datetime import date

from app.db.models import Company, FinancialFact, utcnow
from app.services import mapping_check


def _fact(db, cik, version, n):
    if db.query(Company).filter(Company.cik == cik).first() is None:
        db.add(Company(cik=cik, legal_name=cik, source_url="https://www.sec.gov/",
                       quality_status="ok", first_detected_at=utcnow()))  # fmt: skip
        db.flush()
    for i in range(n):
        db.add(FinancialFact(
            cik=cik, metric="revenue", value=1, unit="USD", currency="USD",
            period_start=date(2014, 1, 1), period_end=date(2014, 3, 31), period_type="duration",
            period_class="quarterly", form_type="10-Q", filed_date=date(2014, 5, 1),
            accession_number=f"{cik[-6:]}-14-{version}-{i:04d}", source_tag="Revenues",
            source_taxonomy="us-gaap", source_url="https://www.sec.gov/Archives/x",
            mapping_version=version, quality_status="ok", derived=False,
            observation_key=uuid.uuid4().hex, first_detected_at=utcnow(),
            processed_at=utcnow(), created_at=utcnow()))  # fmt: skip
    db.commit()


def test_reviewed_exceptions_pass_and_anything_else_fails(db, tmp_path):
    path = tmp_path / "exceptions.csv"
    path.write_text("cik,name,mapping_version,rows,reason,checked_on\n"
                    "0000931182,ERP,1.1.0,3,no longer published,2026-11-22\n")  # fmt: skip
    first = mapping_check.check(db, path)["summary"]
    assert first == "0 unexpected old rows (0 reviewed exceptions)"
    _fact(db, "0000931182", "1.1.0", 3)
    out = mapping_check.check(db, path)
    assert out["ok"] and out["summary"] == "0 unexpected old rows (3 reviewed exceptions)"
    _fact(db, "0000931182", "1.1.0", 1)  # more rows than reviewed
    out = mapping_check.check(db, path)
    assert not out["ok"] and out["unexpected"][0]["reviewed_rows"] == 3
    _fact(db, "0000320193", "1.4.0", 2)  # a company the pass missed
    out = mapping_check.check(db, path)
    assert {u["cik"] for u in out["unexpected"]} == {"0000931182", "0000320193"}


def test_the_shipped_file_lists_the_five_reviewed_companies():
    allowed = mapping_check.reviewed()
    assert sum(allowed.values()) == 122 and len(allowed) == 5
    assert all(v == "1.1.0" for _, v in allowed)
