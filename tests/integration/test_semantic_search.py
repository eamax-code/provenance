"""Chunked, embedded section search (issue #2, step 3). The search itself needs PostgreSQL with
pgvector; chunking is tested everywhere."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.db.models import Company, Filing, FilingSection
from app.services import prospectus as pr
from app.services import semantic_search as sem

S1 = (Path(__file__).parents[1] / "fixtures" / "s1_example.htm").read_text(encoding="utf-8")
CIK = "0002999001"
ACCESSION = "0002999001-26-000002"
INDEX = (
    "https://www.sec.gov/Archives/edgar/data/2999001/000299900126000002/"
    + ACCESSION
    + "-index.html"
)


def test_chunks_end_on_sentences_and_overlap():
    body = " ".join(f"Sentence number {i} says something about the offering." for i in range(200))
    chunks = sem.chunk_text(body, size=400, overlap=80)
    assert len(chunks) > 5 and all(len(c) <= 400 for c in chunks)
    assert all(c.rstrip().endswith(".") for c in chunks[:-1])
    # Each chunk starts with words from the end of the one before it.
    assert chunks[1].split()[0] in chunks[0][-80:]
    assert sem.chunk_text("") == [] and sem.chunk_text("Short.") == ["Short."]
    long_row = "x" * 1000
    assert all(len(c) <= 400 for c in sem.chunk_text(long_row, size=400, overlap=50))


def _fake_vector(text: str, dims: int) -> list[float]:
    """Words hashed into buckets: texts that share words point the same way."""
    v = [0.0] * dims
    for word in text.lower().split():
        v[int(hashlib.md5(word.strip(".,?").encode()).hexdigest(), 16) % dims] += 1.0
    return v


@pytest.fixture
def pg_chunks(db, settings, monkeypatch):
    if db.get_bind().dialect.name != "postgresql":
        pytest.skip("semantic search needs PostgreSQL with pgvector")
    now = datetime.now(UTC)
    db.add(
        Company(
            cik=CIK, legal_name="Lumen Example Labs, Inc.", source_url=INDEX, first_detected_at=now
        )
    )
    db.add(
        Filing(
            cik=CIK,
            accession_number=ACCESSION,
            form_type="S-1",
            filing_date=date(2026, 10, 20),
            source_url=INDEX,
            first_detected_at=now,
            quality_status="ok",
        )
    )
    for item, body in pr.split_sections(S1).items():
        db.add(
            FilingSection(
                cik=CIK,
                accession_number=ACCESSION,
                item=item,
                status="ok",
                text=body,
                source_url=INDEX,
            )
        )
    db.commit()
    monkeypatch.setattr(
        sem,
        "embed",
        lambda s, texts, model, query=False: [_fake_vector(t, sem.MODELS[model][1]) for t in texts],
    )
    assert sem.index_sections(db, settings, sem.DEFAULT_MODEL, log=lambda *_: None) > 0
    return db


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid"])
def test_each_mode_finds_the_section_with_its_filing(pg_chunks, settings, mode):
    hits = sem.search(pg_chunks, settings, "net proceeds working capital Asia", mode=mode, limit=3)
    assert hits and hits[0].cik == CIK and hits[0].source_url == INDEX
    assert {h.item for h in hits} & {"pr:use", "pr:summ"}
    assert hits[0].form_type == "S-1" and hits[0].filing_date == date(2026, 10, 20)


def test_filters_and_reindexing(pg_chunks, settings):
    assert sem.search(pg_chunks, settings, "cloud providers", cik="0000320193") == []
    assert sem.search(pg_chunks, settings, "cloud providers", as_of=date(2026, 10, 19)) == []
    assert sem.search(pg_chunks, settings, "cloud providers", as_of=date(2026, 10, 20))
    # Nothing left to chunk or embed the second time.
    assert sem.index_sections(pg_chunks, settings, sem.DEFAULT_MODEL, log=lambda *_: None) == 0
