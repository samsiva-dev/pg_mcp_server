-- pg-source-explorer schema
-- Run: psql pg_source_index < schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS code_chunks (
    id            SERIAL PRIMARY KEY,
    file_path     TEXT NOT NULL,
    function_name TEXT,
    chunk_text    TEXT NOT NULL,
    embedding     vector(768),
    start_line    INT,
    end_line      INT,
    subsystem     TEXT
);

-- HNSW index for fast approximate cosine similarity search
CREATE INDEX IF NOT EXISTS code_chunks_embedding_idx
ON code_chunks
USING hnsw (embedding vector_cosine_ops);

-- Optional: index for subsystem-scoped queries
CREATE INDEX IF NOT EXISTS code_chunks_subsystem_idx
ON code_chunks (subsystem);
