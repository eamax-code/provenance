"""Semantic and hybrid search over filing sections (issue #2, step 3). PostgreSQL with pgvector.

Sections are cut into overlapping chunks of about CHUNK_CHARS characters on sentence boundaries,
embedded with a local Ollama model and stored in section_chunks (halfvec with an HNSW index).
A query is answered three ways for comparison:

- keyword: the chunk's tsvector against the query's words joined with OR, ranked by ts_rank_cd;
- vector: cosine distance between the query embedding and the chunk embeddings;
- hybrid: both lists fused by reciprocal rank (score = sum of 1 / (RRF_K + rank)).

Hits are chunks; each carries its section, filing form, date, accession number and filing link.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.section_search import section_title

CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200
EMBED_BATCH = 32
CANDIDATES = 50
RRF_K = 60
# Chosen in docs/adr/0008-search-in-postgres.md from the benchmark in docs/benchmarks/.
DEFAULT_MODEL = "bge-m3"
# Model name -> (column, dimensions, document prefix, query prefix).
MODELS = {
    "nomic-embed-text": ("embedding_nomic", 768, "search_document: ", "search_query: "),
    "bge-m3": ("embedding_bge", 1024, "", ""),
}
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"“])")


@dataclass
class ChunkHit:
    cik: str
    accession_number: str
    item: str
    title: str
    form_type: str | None
    filing_date: date | None
    source_url: str
    chunk_no: int
    text: str
    score: float


class EmbeddingUnavailable(RuntimeError):
    pass


def chunk_text(body: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Chunks of about `size` characters that end on sentence boundaries, each starting with
    the last `overlap` characters of the previous one so an idea split across them is kept."""
    body = " ".join(body.split())
    if len(body) <= size:
        return [body] if body else []
    sentences = _SENTENCE_END.split(body)
    chunks, current = [], ""
    for s in sentences:
        while len(s) > size:  # a table row run or a very long sentence
            head, s = s[:size], s[size:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if current and len(current) + 1 + len(s) > size:
            chunks.append(current)
            tail = current[-overlap:]
            current = tail[tail.find(" ") + 1 :] + " " + s if " " in tail else s
        else:
            current = (current + " " + s).strip()
    if current:
        chunks.append(current)
    return chunks


def embed(
    settings: Settings, texts: list[str], model: str, *, query: bool = False
) -> list[list[float]]:
    column, dims, doc_prefix, query_prefix = MODELS[model]
    prefix = query_prefix if query else doc_prefix
    try:
        r = httpx.post(
            settings.llm_base_url.rstrip("/") + "/api/embed",
            json={"model": model, "input": [prefix + t for t in texts], "truncate": True},
            timeout=httpx.Timeout(300.0, connect=3.0),
        )
        r.raise_for_status()
    except httpx.HTTPError as exc:
        raise EmbeddingUnavailable(f"The embedding model {model} could not be reached.") from exc
    vectors = r.json()["embeddings"]
    if any(len(v) != dims for v in vectors):
        raise EmbeddingUnavailable(f"{model} returned vectors of an unexpected size.")
    return vectors


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def index_sections(
    db: Session, settings: Settings, model: str, *, ciks: list[str] | None = None, log=print
) -> int:
    """Chunk every searchable section not chunked yet, then embed the chunks this model has no
    vector for. Returns the number of chunks embedded."""
    column = MODELS[model][0]
    scope = "AND s.cik = ANY(:ciks)" if ciks else ""
    params = {"ciks": ciks} if ciks else {}
    sections = db.execute(
        text(
            f"""SELECT s.id, s.cik, s.accession_number, s.item, s.text FROM filing_sections s
            WHERE s.status = 'ok' AND s.text IS NOT NULL {scope}
              AND NOT EXISTS (SELECT 1 FROM section_chunks c WHERE c.section_id = s.id)"""
        ),
        params,
    ).all()
    for sid, cik, accession, item, body in sections:
        rows = [
            {"sid": sid, "cik": cik, "acc": accession, "item": item, "n": n, "text": chunk}
            for n, chunk in enumerate(chunk_text(body))
        ]
        if rows:
            db.execute(
                text(
                    "INSERT INTO section_chunks (section_id, cik, accession_number, item, chunk_no,"
                    " text) VALUES (:sid, :cik, :acc, :item, :n, :text)"
                    " ON CONFLICT (section_id, chunk_no) DO NOTHING"
                ),
                rows,
            )
    db.commit()
    if sections:
        log(f"chunked {len(sections)} sections")
    todo = db.execute(
        text(
            f"SELECT c.id, c.text FROM section_chunks c WHERE c.{column} IS NULL"
            + (" AND c.cik = ANY(:ciks)" if ciks else "")
            + " ORDER BY c.id"
        ),
        params,
    ).all()
    done, started = 0, time.perf_counter()
    for i in range(0, len(todo), EMBED_BATCH):
        batch = todo[i : i + EMBED_BATCH]
        vectors = embed(settings, [t for _, t in batch], model)
        db.execute(
            text(f"UPDATE section_chunks SET {column} = CAST(:v AS halfvec) WHERE id = :id"),
            [{"id": cid, "v": _vec(v)} for (cid, _), v in zip(batch, vectors, strict=True)],
        )
        db.commit()
        done += len(batch)
        if done % (EMBED_BATCH * 20) == 0 or done == len(todo):
            rate = done / max(time.perf_counter() - started, 1e-6)
            log(f"{model}: {done}/{len(todo)} chunks, {rate:.0f}/s")
    return done


def search(
    db: Session,
    settings: Settings,
    query: str,
    *,
    mode: str = "vector",
    model: str = DEFAULT_MODEL,
    cik: str | None = None,
    as_of: date | None = None,
    limit: int = 10,
    keyword_weight: float = 1.0,
) -> list[ChunkHit]:
    """Chunks that answer the query, best first, by keyword, vector or hybrid ranking. In hybrid
    ranking the keyword list counts `keyword_weight` times as much as the vector list."""
    if mode == "keyword":
        ranked = _keyword(db, query, cik, as_of, limit)
    elif mode == "vector":
        ranked = _vector(db, settings, query, model, cik, as_of, limit)
    else:
        kw = _keyword(db, query, cik, as_of, CANDIDATES)
        vec = _vector(db, settings, query, model, cik, as_of, CANDIDATES)
        fused: dict[int, float] = {}
        for ranking, weight in ((kw, keyword_weight), (vec, 1.0)):
            for rank, (cid, _) in enumerate(ranking, start=1):
                fused[cid] = fused.get(cid, 0.0) + weight / (RRF_K + rank)
        ranked = sorted(fused.items(), key=lambda x: -x[1])[:limit]
    return _hydrate(db, ranked)


_FILTERS = """
    JOIN filings f ON f.cik = c.cik AND f.accession_number = c.accession_number
    WHERE (CAST(:cik AS varchar) IS NULL OR c.cik = :cik)
      AND (CAST(:as_of AS date) IS NULL OR f.filing_date <= :as_of)
"""


def _keyword(db: Session, query: str, cik, as_of, limit) -> list[tuple[int, float]]:
    # Any of the query's words, so a paraphrase still finds candidates; rank decides.
    rows = db.execute(
        text(
            """WITH q AS (SELECT CAST(
                replace(CAST(plainto_tsquery('english', :q) AS text), '&', '|') AS tsquery
            ) AS tsq)
            SELECT c.id, ts_rank_cd(c.search_vector, q.tsq, 32) AS r
            FROM section_chunks c CROSS JOIN q"""
            + _FILTERS
            + """ AND q.tsq <> CAST('' AS tsquery) AND c.search_vector @@ q.tsq
            ORDER BY r DESC LIMIT :limit"""
        ),
        {"q": query, "cik": cik, "as_of": as_of, "limit": limit},
    ).all()
    return [(cid, float(r)) for cid, r in rows]


def _vector(db: Session, settings, query, model, cik, as_of, limit) -> list[tuple[int, float]]:
    column = MODELS[model][0]
    qv = _vec(embed(settings, [query], model, query=True)[0])
    # A wider HNSW search when a filter will discard most neighbours.
    db.execute(text("SET LOCAL hnsw.ef_search = 200"))
    rows = db.execute(
        text(
            f"""SELECT c.id, 1 - (c.{column} <=> CAST(:qv AS halfvec)) AS sim
            FROM section_chunks c"""
            + _FILTERS
            + f""" AND c.{column} IS NOT NULL
            ORDER BY c.{column} <=> CAST(:qv AS halfvec) LIMIT :limit"""
        ),
        {"qv": qv, "cik": cik, "as_of": as_of, "limit": limit},
    ).all()
    return [(cid, float(s)) for cid, s in rows]


def _hydrate(db: Session, ranked: list[tuple[int, float]]) -> list[ChunkHit]:
    if not ranked:
        return []
    ids = [cid for cid, _ in ranked]
    rows = {
        r.id: r
        for r in db.execute(
            text(
                """SELECT c.id, c.cik, c.accession_number, c.item, c.chunk_no, c.text,
                       f.form_type, f.filing_date, s.source_url
                FROM section_chunks c
                JOIN filing_sections s ON s.id = c.section_id
                JOIN filings f ON f.cik = c.cik AND f.accession_number = c.accession_number
                WHERE c.id = ANY(:ids)"""
            ),
            {"ids": ids},
        )
    }
    return [
        ChunkHit(
            cik=r.cik,
            accession_number=r.accession_number,
            item=r.item,
            title=section_title(r.item),
            form_type=r.form_type,
            filing_date=r.filing_date,
            source_url=r.source_url,
            chunk_no=r.chunk_no,
            text=r.text,
            score=round(score, 5),
        )
        for cid, score in ranked
        if (r := rows.get(cid)) is not None
    ]
