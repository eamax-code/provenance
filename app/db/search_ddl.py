"""PostgreSQL-only DDL for search (pgvector), shared by the migration and the test schema."""

CHUNKS_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS section_chunks (
    id bigserial PRIMARY KEY,
    section_id uuid NOT NULL REFERENCES filing_sections(id) ON DELETE CASCADE,
    cik varchar(10) NOT NULL,
    accession_number varchar(25) NOT NULL,
    item varchar(10) NOT NULL,
    chunk_no integer NOT NULL,
    text text NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, text)) STORED,
    embedding_nomic halfvec(768),
    embedding_bge halfvec(1024),
    UNIQUE (section_id, chunk_no)
);
CREATE INDEX IF NOT EXISTS ix_section_chunks_cik ON section_chunks (cik);
CREATE INDEX IF NOT EXISTS ix_section_chunks_search ON section_chunks USING gin (search_vector);
CREATE INDEX IF NOT EXISTS ix_section_chunks_nomic ON section_chunks
    USING hnsw (embedding_nomic halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS ix_section_chunks_bge ON section_chunks
    USING hnsw (embedding_bge halfvec_cosine_ops);
"""
