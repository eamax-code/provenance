# ADR 0008: Search stays in PostgreSQL; meaning-based search uses bge-m3 vectors

**Status:** accepted (2026-11-05)

Issue #2 asked whether lookup and search can stay in PostgreSQL or need a separate engine, and
which retrieval works best on filing text: keyword, vector or a hybrid of the two.

**What was built.**
- Company names: a trigram index (`pg_trgm`) and typo matching ranked by edit distance (step 1).
- Keyword search: a stored `tsvector` per section with a GIN index (step 2).
- Vector search (step 3): the 1,227 stored sections are cut into 51,764 chunks of about 1,500
  characters with 200 characters of overlap, on sentence boundaries. Each chunk is embedded
  locally through Ollama with two models, `nomic-embed-text` (768 dimensions) and `bge-m3`
  (1,024), stored as `halfvec` with an HNSW index (pgvector 0.8.7 on the `pgvector/pgvector:pg16`
  image).

**The benchmark** (`scripts/bench_search.py`, results in `docs/benchmarks/search-2026-11.md`).
- 30 questions: three companies for each of ten prospectus sections, phrased without the
  section's title words ("Which banks are selling X's shares?" for underwriting).
- Each question runs within its company (top 3) and across all companies (top 5).
- "Strict" counts only the expected section; "lenient" also accepts the prospectus summary,
  which repeats most sections in short.

| Setup | Within company, strict / lenient | Across companies, strict / lenient | p50 / p95 |
|---|---|---|---|
| keyword (any word) | 27% / 60% | 0% / 10% | 15 / 213 ms |
| vector, nomic-embed-text | 27% / 83% | 30% / 83% | 84 / 93 ms |
| **vector, bge-m3** | **47% / 90%** | **33% / 83%** | 179 / 243 ms |
| hybrid (RRF), nomic | 33% / 77% | 17% / 53% | 73 / 319 ms |
| hybrid (RRF), bge-m3 | 37% / 77% | 23% / 70% | 186 / 434 ms |
| hybrid, bge-m3, keyword weight 0.15 | 43% / 90% | 33% / 80% | |

Of bge-m3's 179 ms, about 121 ms is embedding the question in Ollama and about 60 ms (p95 71 ms)
is the HNSW search and join in PostgreSQL. Embedding all chunks took 16 minutes with nomic
(54 chunks/s) and 43 minutes with bge-m3 (20 chunks/s) on an M4 Pro. Storage: the chunk table is
618 MB, the HNSW indexes 99 MB (nomic) and 132 MB (bge-m3), the GIN index 23 MB.

**Decision.**
- Keep all search in PostgreSQL. Latency is well inside the targets, and the database keeps
  point-in-time filters, company filters and filing links in the same query. Meilisearch is not
  needed now; revisit only for search-as-you-type over far larger text.
- Meaning-based questions use vector search with `bge-m3`. It finds the right section for 90%
  of paraphrased questions within a company (lenient), against 60% for keyword search.
- Exact-term lookups (a phrase, a name, an accession number) keep the full-text section search
  from step 2, which needs every word and ranks well when the words are known.
- Hybrid fusion is not used. Keyword search on paraphrased questions mostly adds noise, so even
  at a low weight it did not beat vectors alone. Re-test if the question mix changes.

**Consequences.**
- New sections must be embedded: run `scripts/embed_sections.py --model bge-m3` after
  prospectus reading, at about 20 chunks a second. The nomic column stays until a re-test.
- Queries depend on the local Ollama embedding model. When it is down, vector search fails and
  callers fall back to keyword search.
- Retrieval quality across all companies is the weak point (33% strict): the right company's
  summary is often found, but not the exact section. Filtering by company first, as the chat
  does, is the reliable path.
