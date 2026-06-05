# pg-source-explorer

A local, free PostgreSQL internals assistant — semantic search over PG source
code, integrated into Zed and VSCode via MCP.

Ask natural language questions about PostgreSQL internals and get answers
grounded in the actual C source on your machine. No API costs. No internet.

```
Use the ask_pg tool to explain how PostgreSQL evicts dirty buffers
```

```
ReadBuffer is a thin wrapper around ReadBufferExtended in src/backend/storage/buffer/bufmgr.c.
It always calls ReadBufferExtended(reln, MAIN_FORKNUM, blockNum, RBM_NORMAL, NULL).
When the requested block isn't in shared_buffers, StrategyGetBuffer() runs the
clock-sweep algorithm to find a victim buffer...
```

---

## What's Inside

Three tools exposed via MCP:

| Tool | What it does |
|---|---|
| `ask_pg` | RAG — semantic search + LLM answer grounded in PG source |
| `search_pg` | Raw semantic search — returns top-k source chunks |
| `search_symbol` | cscope lookup — callers, definition, references, callees |

---

## Stack

```
ctags + cscope        → deterministic symbol navigation
pgvector on PG 18     → HNSW semantic search over 33,734 source chunks
nomic-embed-text      → 768-dim embeddings (via Ollama)
qwen2.5-coder:7b      → local LLM reasoning (via Ollama, ~4.5GB RAM)
FastMCP               → exposes tools to Zed / VSCode Agent Panel
```

Everything runs locally. No OpenAI, no Anthropic API, no data leaving your machine.

---

## Requirements

- macOS ARM64 (Apple Silicon) or Linux
- PostgreSQL 18 with pgvector extension
- Ollama
- Python 3.11+
- Zed or VSCode with GitHub Copilot (Agent mode)
- PostgreSQL source code

---

## Setup

### 1. Install Ollama and pull models

```bash
# Install via official installer (not Homebrew)
curl -fsSL https://ollama.com/install.sh | sh

ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

### 2. Install pgvector

```bash
brew install pgvector   # macOS
# or: apt install postgresql-18-pgvector  # Ubuntu
```

### 3. Create the database schema

```bash
psql -c "CREATE DATABASE pg_source_index;"
psql pg_source_index < schema.sql
```

### 4. Build ctags + cscope index

```bash
brew install cscope universal-ctags

cd /path/to/postgresql-source

ctags -R --languages=C --fields=+iaS --extras=+q .

find . -name "*.c" -o -name "*.h" | xargs ls 2>/dev/null > cscope.files
cscope -b -q -k
```

### 5. Set up Python environment

```bash
python3 -m venv ~/pg-tools-env
source ~/pg-tools-env/bin/activate
pip install psycopg2-binary requests mcp
```

### 6. Configure paths

Edit the config block at the top of both scripts:

```python
# index_pg_source.py and pg_mcp_server.py
PG_CONN = "dbname=pg_source_index"      # your PG connection string
PG_SRC  = "/path/to/postgresql"         # PG source root (where cscope.out lives)
```

### 7. Run the indexer (one-time, ~15–30 min)

```bash
ollama serve &
python index_pg_source.py
```

Verify:
```sql
SELECT COUNT(*) FROM code_chunks;
-- 33734
```

### 8. Configure your editor

**Zed** — add to `settings.json`:

```json
{
  "context_servers": {
    "pg-source-explorer": {
      "source": "custom",
      "command": {
        "path": "/Users/yourname/pg-tools-env/bin/python",
        "args": ["/path/to/pg_mcp_server.py"]
      }
    }
  }
}
```

**VSCode** — create `~/.vscode/mcp.json`:

```json
{
  "servers": {
    "pg-source-explorer": {
      "type": "stdio",
      "command": "/Users/yourname/pg-tools-env/bin/python",
      "args": ["/path/to/pg_mcp_server.py"],
      "env": {}
    }
  }
}
```

Open the file in VSCode and click the **Start** CodeLens button.

---

## Daily Workflow

```bash
# Start session
source ~/pg-tools-env/bin/activate
ollama serve

# Stop when done (Ctrl+C or)
pkill ollama
```

Then in the Agent Panel:

```
Use the ask_pg tool to explain how XLogInsert works
Use search_pg to find code related to predicate locking
Use search_symbol to find who calls StrategyGetBuffer
```

---

## File Structure

```
pg-source-explorer/
├── README.md
├── schema.sql              ← pgvector table + HNSW index
├── index_pg_source.py      ← chunks PG source + stores embeddings
├── ask_pg.py               ← CLI query interface
└── pg_mcp_server.py        ← MCP server (Zed / VSCode integration)
```

---

## Subsystems

The indexer labels chunks by subsystem for scoped queries:

| Subsystem | Source path |
|---|---|
| `buffer` | `storage/buffer/` |
| `wal` | `access/transam/`, `replication/walreceiver/` |
| `executor` | `executor/` |
| `mvcc` | `access/transam/` |
| `heap` | `access/heap/` |
| `storage` | `storage/smgr/` |
| `locking` | `storage/lmgr/` |
| `other` | everything else |

---

## Limitations

- `qwen2.5-coder:7b` is a 7B model — good for code explanation, not deep
  architecture reasoning. Use a hosted model (Claude, GPT-4) for design decisions.
- Chunking is function-level. Cross-file patterns need multiple queries.
- Generated files (`fmgroids.h`, `nodetags.h`) are excluded unless you build
  PG from source first.
- Index is built once — re-run `index_pg_source.py` after upgrading PG source.

---

## License

MIT
