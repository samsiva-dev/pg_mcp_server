"""
pg_mcp_server.py
MCP server exposing PostgreSQL source RAG as tools for Zed Agent Panel.

Tools exposed:
  - ask_pg        : natural language Q&A over indexed PG source
  - search_pg     : raw semantic search — returns top-k chunks
  - search_symbol : cscope symbol lookup (who calls X, where defined)

Usage:
  python pg_mcp_server.py
"""

import subprocess

import psycopg2
import requests
from mcp.server.fastmcp import FastMCP

# ── Config ─────────────────────────────────────────────────────────────────
PG_CONN = "host=localhost port=5432 dbname=pg_source_index"  # update if needed
OLLAMA = "http://localhost:11434"
EMB_MODEL = "nomic-embed-text"
CHAT_MODEL = "qwen2.5-coder:7b"
TOP_K = 5
PG_SRC = "/Users/sambasiva/Projects/postgres"  # path where cscope.out lives
# ───────────────────────────────────────────────────────────────────────────

mcp = FastMCP("pg-source-explorer")


# ── Helpers ────────────────────────────────────────────────────────────────


def embed(text: str) -> list[float]:
    resp = requests.post(
        f"{OLLAMA}/api/embeddings", json={"model": EMB_MODEL, "prompt": text[:2000]}
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def vector_search(query: str, subsystem: str | None = None, top_k: int = TOP_K):
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
            (q_embed, subsystem, q_embed, top_k),
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
            (q_embed, q_embed, top_k),
        )

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# ── Tools ──────────────────────────────────────────────────────────────────


@mcp.tool()
def ask_pg(question: str, subsystem: str = "") -> str:
    """
    Ask a natural language question about PostgreSQL internals.
    Searches the indexed PG source code and returns an LLM answer
    grounded in actual source context.

    Args:
        question  : Your question about PG internals.
                    e.g. "How does PostgreSQL evict dirty buffers?"
        subsystem : Optional filter for focused search.
                    One of: buffer, wal, executor, mvcc, heap, storage, locking
                    Leave empty to search all subsystems.
    """
    sub = subsystem.strip() or None
    results = vector_search(question, subsystem=sub)

    if not results:
        return "No relevant source chunks found. Make sure the index is built."

    context = "\n\n---\n\n".join(
        [
            f"File: {r[0]}\nFunction: {r[1]}\nSubsystem: {r[3]}\nSimilarity: {r[4]:.3f}\n\n{r[2]}"
            for r in results
        ]
    )

    prompt = f"""You are an expert in PostgreSQL internals at the C source code level.
Use the following source code context to answer the question precisely.
Always reference specific function names and file paths in your answer.

CONTEXT:
{context}

QUESTION: {question}

Answer:"""

    resp = requests.post(
        f"{OLLAMA}/api/generate",
        json={"model": CHAT_MODEL, "prompt": prompt, "stream": False},
    )
    resp.raise_for_status()
    return resp.json()["response"]


@mcp.tool()
def search_pg(query: str, subsystem: str = "", top_k: int = 5) -> str:
    """
    Semantic search over indexed PostgreSQL source code.
    Returns the top matching code chunks with file paths and similarity scores.
    Useful when you want to read the raw source rather than a generated answer.

    Args:
        query     : What to search for. e.g. "buffer eviction clock sweep"
        subsystem : Optional filter. One of: buffer, wal, executor, mvcc,
                    heap, storage, locking. Leave empty for all.
        top_k     : Number of results to return (default 5, max 10).
    """
    sub = subsystem.strip() or None
    k = min(top_k, 10)
    results = vector_search(query, subsystem=sub, top_k=k)

    if not results:
        return "No results found."

    output = []
    for i, r in enumerate(results, 1):
        output.append(
            f"── Result {i} ──────────────────────────\n"
            f"File      : {r[0]}\n"
            f"Function  : {r[1]}\n"
            f"Subsystem : {r[3]}\n"
            f"Similarity: {r[4]:.3f}\n\n"
            f"{r[2][:800]}{'...' if len(r[2]) > 800 else ''}"
        )

    return "\n\n".join(output)


@mcp.tool()
def search_symbol(symbol: str, search_type: str = "callers") -> str:
    """
    Look up a C symbol in the PostgreSQL source using cscope.
    Finds callers, definition, or all references of a function/variable.

    Args:
        symbol      : The C symbol to look up. e.g. "ReadBuffer", "BufMgrLock"
        search_type : One of:
                        "callers"     - functions that call this symbol
                        "definition"  - where this symbol is defined
                        "references"  - all references to this symbol
                        "callees"     - functions called by this symbol
    """
    type_map = {
        "callers": "3",
        "definition": "1",
        "references": "0",
        "callees": "2",
    }

    flag = type_map.get(search_type, "3")

    try:
        result = subprocess.run(
            ["cscope", "-d", "-f", f"{PG_SRC}/cscope.out", "-L", f"-{flag}", symbol],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if not result.stdout.strip():
            return f"No {search_type} found for symbol '{symbol}'."

        lines = result.stdout.strip().split("\n")
        output = [f"cscope {search_type} for '{symbol}':\n"]
        for line in lines[:30]:  # cap at 30 results
            parts = line.split()
            if len(parts) >= 3:
                file_path, fn_name, line_num = parts[0], parts[1], parts[2]
                output.append(f"  {file_path}:{line_num}  (in {fn_name})")
            else:
                output.append(f"  {line}")

        if len(lines) > 30:
            output.append(f"\n  ... and {len(lines) - 30} more results")

        return "\n".join(output)

    except FileNotFoundError:
        return "cscope not found. Install with: brew install cscope"
    except subprocess.TimeoutExpired:
        return "cscope query timed out."


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting pg-source-explorer MCP server...")
    print(f"  Chat model : {CHAT_MODEL}")
    print(f"  Embed model: {EMB_MODEL}")
    print(f"  PG conn    : {PG_CONN}")
    print(f"  PG src     : {PG_SRC}")
    mcp.run(transport="stdio")
