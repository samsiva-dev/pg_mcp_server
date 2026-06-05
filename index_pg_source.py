import os
import re

import psycopg2
import requests

# ── Config ──────────────────────────────────────────
PG_CONN = "host=localhost port=5432 dbname=pg_source_index"
PG_SRC = "/Users/sambasiva/Projects/postgres"
OLLAMA = "http://localhost:11434"
EMB_MODEL = "nomic-embed-text"  # embedding model
# ────────────────────────────────────────────────────

SUBSYSTEMS = {
    "storage/buffer": "buffer",
    "storage/smgr": "storage",
    "access/heap": "heap",
    "executor": "executor",
    "storage/lmgr": "locking",
    "access/transam": "mvcc",
    "replication/walreceiver": "wal",
    "access/rmgrdesc": "wal",
}


def get_subsystem(path):
    for pattern, name in SUBSYSTEMS.items():
        if pattern in path:
            return name
    return "other"


def extract_functions(content):
    """Split C file into function-level chunks."""
    chunks = []
    lines = content.split("\n")
    current_chunk = []
    current_start = 1
    brace_depth = 0
    in_function = False

    for i, line in enumerate(lines, 1):
        current_chunk.append(line)
        brace_depth += line.count("{") - line.count("}")

        if brace_depth == 0 and in_function:
            chunk_text = "\n".join(current_chunk)
            if len(chunk_text.strip()) > 50:
                chunks.append((chunk_text, current_start, i))
            current_chunk = []
            current_start = i + 1
            in_function = False
        elif brace_depth > 0:
            in_function = True

    return chunks


def embed(text):
    resp = requests.post(
        f"{OLLAMA}/api/embeddings", json={"model": EMB_MODEL, "prompt": text[:2000]}
    )
    return resp.json()["embedding"]


def index_file(cur, filepath):
    with open(filepath, "r", errors="ignore") as f:
        content = f.read()

    subsystem = get_subsystem(filepath)
    chunks = extract_functions(content)

    for chunk_text, start, end in chunks:
        match = re.search(r"^(\w+)\s*\(", chunk_text, re.MULTILINE)
        fn_name = match.group(1) if match else None
        embedding = embed(chunk_text)

        cur.execute(
            """
            INSERT INTO code_chunks
                (file_path, function_name, chunk_text, embedding, start_line, end_line, subsystem)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
            (filepath, fn_name, chunk_text, embedding, start, end, subsystem),
        )


def main():
    conn = psycopg2.connect(PG_CONN)
    conn.autocommit = True
    cur = conn.cursor()

    c_files = []
    for root, _, files in os.walk(PG_SRC):
        for f in files:
            if f.endswith(".c") or f.endswith(".h"):
                c_files.append(os.path.join(root, f))

    print(f"Indexing {len(c_files)} files...")
    for i, fp in enumerate(c_files):
        print(f"[{i + 1}/{len(c_files)}] {fp}")
        try:
            index_file(cur, fp)
        except Exception as e:
            print(f"  ERROR: {e}")

    print("Done.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
