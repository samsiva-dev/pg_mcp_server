import sys

import psycopg2
import requests

# ── Config ──────────────────────────────────────────
PG_CONN = "host=localhost port=5432 dbname=pg_source_index"
OLLAMA = "http://localhost:11434"
EMB_MODEL = "nomic-embed-text"
CHAT_MODEL = "qwen2.5-coder:7b"  # updated from deepseek-coder-v2
TOP_K = 5
# ────────────────────────────────────────────────────


def embed(text):
    resp = requests.post(
        f"{OLLAMA}/api/embeddings", json={"model": EMB_MODEL, "prompt": text}
    )
    return resp.json()["embedding"]


def search(query, subsystem=None):
    conn = psycopg2.connect(PG_CONN)
    cur = conn.cursor()
    q_embed = str(embed(query))

    if subsystem:
        cur.execute(
            """
            SELECT file_path, function_name, chunk_text, subsystem,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM code_chunks
            WHERE subsystem = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """,
            (q_embed, subsystem, q_embed, TOP_K),
        )
    else:
        cur.execute(
            """
            SELECT file_path, function_name, chunk_text, subsystem,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM code_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """,
            (q_embed, q_embed, TOP_K),
        )

    return cur.fetchall()


def ask(question, subsystem=None):
    results = search(question, subsystem)

    context = "\n\n---\n\n".join(
        [
            f"File: {r[0]}\nFunction: {r[1]}\nSubsystem: {r[3]}\n\n{r[2]}"
            for r in results
        ]
    )

    prompt = f"""You are an expert in PostgreSQL internals (C source code level).
Use the following source code context to answer the question precisely.
Reference specific function names and file paths in your answer.

CONTEXT:
{context}

QUESTION: {question}

Answer:"""

    resp = requests.post(
        f"{OLLAMA}/api/generate",
        json={"model": CHAT_MODEL, "prompt": prompt, "stream": False},
    )
    print("\n" + resp.json()["response"])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python ask_pg.py "your question here"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    # Optional: pass subsystem as env or second arg
    # e.g. python ask_pg.py "how does WAL flush work" wal
    subsystem = sys.argv[2] if len(sys.argv) > 2 else None
    ask(question, subsystem)
