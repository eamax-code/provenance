"""Benchmark keyword, vector and hybrid search over filing sections (issue #2, step 3).

Thirty questions, three companies for each of ten prospectus sections, written without the
section's title words so they test meaning rather than word overlap. Each question runs twice:
within its company (as the chat uses search) and across all companies. A hit is a chunk from the
expected section of the expected company; "lenient" also accepts the prospectus summary, which
repeats most sections in short.

    python scripts/bench_search.py --out docs/benchmarks/search-2026-11.md
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from _bootstrap import bootstrap
from sqlalchemy import text

from app.services import semantic_search as sem
from app.services.intel import display_name

QUESTIONS = {
    "pr:use": "How will {n} spend the money from selling its shares?",
    "pr:risk": "What could go badly wrong for {n}?",
    "pr:owner": "Who holds the largest stakes in {n}?",
    "pr:div": "Will {n} pay cash to its shareholders?",
    "pr:dil": "How much less is each new share of {n} backed by than the price buyers pay?",
    "pr:uw": "Which banks are selling {n}'s shares to investors?",
    "pr:pay": "How much were {n}'s top executives paid?",
    "pr:mgmt": "Who are the people running {n}?",
    "pr:cap": "How much debt and equity will {n} have after the deal?",
    "pr:biz": "What does {n} sell and to whom?",
}
SETUPS = [
    ("keyword", "keyword", "nomic-embed-text"),
    ("vector, nomic-embed-text", "vector", "nomic-embed-text"),
    ("vector, bge-m3", "vector", "bge-m3"),
    ("hybrid, nomic-embed-text", "hybrid", "nomic-embed-text"),
    ("hybrid, bge-m3", "hybrid", "bge-m3"),
]
PER_ITEM = 3


def pick_questions(db) -> list[dict]:
    rng = random.Random(20261105)
    out = []
    for item, template in QUESTIONS.items():
        rows = db.execute(
            text(
                """SELECT c.cik, co.legal_name FROM section_chunks c
                JOIN companies co ON co.cik = c.cik
                WHERE c.item = :item AND c.embedding_nomic IS NOT NULL
                  AND c.embedding_bge IS NOT NULL
                GROUP BY c.cik, co.legal_name ORDER BY c.cik"""
            ),
            {"item": item},
        ).all()
        for cik, name in rng.sample(rows, min(PER_ITEM, len(rows))):
            short = display_name(name).replace(", Inc.", "").replace(" Inc.", "")
            out.append({"item": item, "cik": cik, "q": template.format(n=short)})
    return out


def rank_of(hits, cik: str, items: set[str]) -> int | None:
    for i, h in enumerate(hits, start=1):
        if h.cik == cik and h.item in items:
            return i
    return None


def run(db, settings, questions) -> dict:
    results = {}
    for label, mode, model in SETUPS:
        rows, times = [], []
        for q in questions:
            for scope, cik, k in (("within", q["cik"], 3), ("across", None, 5)):
                t = time.perf_counter()
                hits = sem.search(db, settings, q["q"], mode=mode, model=model, cik=cik, limit=k)
                times.append((time.perf_counter() - t) * 1000)
                db.rollback()
                strict = rank_of(hits, q["cik"], {q["item"]})
                lenient = rank_of(hits, q["cik"], {q["item"], "pr:summ"})
                rows.append({**q, "scope": scope, "strict": strict, "lenient": lenient})
        results[label] = {"rows": rows, "ms": times}
    return results


def summarise(results: dict) -> list[dict]:
    table = []
    for label, r in results.items():
        line = {"setup": label}
        for scope in ("within", "across"):
            rows = [x for x in r["rows"] if x["scope"] == scope]
            line[f"{scope}_strict"] = sum(1 for x in rows if x["strict"]) / len(rows)
            line[f"{scope}_lenient"] = sum(1 for x in rows if x["lenient"]) / len(rows)
            line[f"{scope}_mrr"] = statistics.mean(
                1 / x["strict"] if x["strict"] else 0 for x in rows
            )
        ms = sorted(r["ms"])
        line["p50_ms"] = statistics.median(ms)
        line["p95_ms"] = ms[int(len(ms) * 0.95) - 1]
        table.append(line)
    return table


def sizes(db) -> dict:
    row = db.execute(
        text(
            """SELECT count(*), count(embedding_nomic), count(embedding_bge),
                pg_size_pretty(pg_total_relation_size('section_chunks')),
                pg_size_pretty(pg_relation_size('ix_section_chunks_nomic')),
                pg_size_pretty(pg_relation_size('ix_section_chunks_bge')),
                pg_size_pretty(pg_relation_size('ix_section_chunks_search'))
            FROM section_chunks"""
        )
    ).one()
    keys = ["chunks", "with_nomic", "with_bge", "table_total", "hnsw_nomic", "hnsw_bge", "gin"]
    return dict(zip(keys, row, strict=True))


def markdown(table: list[dict], questions: list[dict], stats: dict) -> str:
    pct = lambda v: f"{v * 100:.0f}%"  # noqa: E731
    lines = [
        "| Setup | Within company: hit@3 (strict / lenient) | MRR | Across companies: hit@5 "
        "(strict / lenient) | MRR | p50 ms | p95 ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in table:
        lines.append(
            f"| {t['setup']} | {pct(t['within_strict'])} / {pct(t['within_lenient'])} | "
            f"{t['within_mrr']:.2f} | {pct(t['across_strict'])} / {pct(t['across_lenient'])} | "
            f"{t['across_mrr']:.2f} | {t['p50_ms']:.0f} | {t['p95_ms']:.0f} |"
        )
    lines += ["", f"Index: {json.dumps(stats, default=str)}", "", "Questions:", ""]
    lines += [f"- `{q['item']}` {q['q']}" for q in questions]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="Write the results table (markdown) here")
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    try:
        questions = pick_questions(db)
        results = run(db, settings, questions)
        table = summarise(results)
        report = markdown(table, questions, sizes(db))
        print(report)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(report)
            Path(args.out).with_suffix(".json").write_text(
                json.dumps({"table": table, "results": results}, indent=1, default=str)
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
