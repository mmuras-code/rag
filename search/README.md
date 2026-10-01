# search

Ingests Obsidian notes, embeds them, stores them in pgvector and answers semantic queries.
This is the retrieval part of RAG.

Status: P1 built. `just run` syncs the vault into pgvector and serves hybrid search as the
`search.v1.Search` gRPC service on port 8001 (`SEARCH_PORT`).
`just up` starts pgvector first and runs it in the background (log in
`logs/search.log` at the `rag/` root); `just down` stops the server and pgvector.
The contract is `../proto/src/contracts/search/v1/search.proto`; `src/search/server.py`
implements its generated servicer. Callers use the generated client through
`contracts.search.SearchClient` (`SearchClient().query(text, k)`, address `SEARCH_ADDRESS`) and
never import this project. `just query "text" 5` runs one query that way.

## Function

- **Collections:** `SEARCH_VAULT_PATH` is the vault root: any folder of Markdown (`.md`) notes,
  e.g. an Obsidian vault. Only the
  folders named in `SEARCH_COLLECTIONS` under it are read (default: every
  `common.collection.Collection`: `ml`, and `test` for made-up eval facts). Nothing else in the
  vault is read or sent to the embedding model. Paths start with the collection
  (`ml/theoretical/rag/x.md`). A missing collection folder stops the sync rather than deleting
  that collection's rows.
- **P1:** one vector per note, no chunking. Read vault → strip frontmatter → embed (title +
  body, wikilink text kept) → upsert.
- **Sync** is incremental: a content hash per note, so only new or changed notes are embedded
  and rows for removed notes are deleted; a note is re-embedded when its hash or the embedding
  model differs from the stored row. An unchanged vault makes no embedding calls. A note that
  fails to embed (an OpenRouter error, e.g. over the token limit, or a network error) is logged
  and skipped, not stored, so the next sync retries it; the sync ends with a summary line
  (embedded, failed, deleted). Sync is its own command; startup calls the same command, so one
  bad note does not stop the server from starting.
- **Query:** hybrid. A vector ranking (cosine similarity to the embedded query, exact, over all
  notes) and a BM25 ranking (keyword match, computed in Python per query; `src/search/bm25.py`)
  are fused with reciprocal rank fusion, k=60 (`src/search/hybrid.py`). Each result has the RRF
  `score` (ordering only), the cosine `similarity` (use it for relevance thresholds) and the
  `bm25` score. Postgres full-text ranking is not BM25 and the pgvector image has no BM25
  extension; the vault is small enough (about 90 notes) to rank in Python.
- **Collection filter:** a request may name one `collection`; both rankings then cover only its
  notes. Unset searches every indexed collection.
- **Request validation:** `query` must be non-empty, `k` is 1 to 50 (an unset `k`, which
  proto3 reads as 0, means 5) and `collection` empty or indexed; anything else is answered
  INVALID_ARGUMENT.
- Table: `notes(path PK, content_hash, content, embedding vector, model, token_count, truncated,
  updated_at)`. The `embedding` column is untyped `vector` (no fixed dimension), so models with
  different dimensions can be stored; queries filter by `model`. The stored `model` triggers a
  full re-embed when the model changes.
- Token count is logged per note, and notes truncated by the embedding model's limit are flagged.
- **Telemetry:** `sync` and `serve` call `setup_telemetry("search")` (service `search`, the pod
  from `POD_NAME` or the hostname). Each query is the `search.query` operation (an invalid request
  counts as an error, a failed embedding as a fault) and its steps are timed into `ml.time`:
  `search.embed`, `search.vector`, `search.bm25`, `search.fuse`. Each sync is `search.sync`. The
  gRPC server instrumentation continues the agent's trace, so a query is a span in the chat's
  trace. See [`../docs/telemetry.md`](../docs/telemetry.md).

## Runtime

- pgvector in Docker with a named volume, so vectors survive restarts. This is the reason the
  service keeps running while the rest of the system restarts.
- Vault root, collections and database connection string are environment variables. The vault is read-only.
- Embeddings come from OpenRouter through `llm.embed` (`openai/text-embedding-3-small` by
  default, `LLM_EMBED_MODEL`), so `OR_KEY` must be set and note text is sent to
  the hosted model.

## TODO

- **Chunking.** One vector per note is deliberate for P1: the vault is small (about 90 notes)
  and most notes are short and on one topic. The known costs: a note over the embedding model's
  input limit (8191 tokens for `text-embedding-3-small`) is embedded truncated, so its tail
  cannot be found; a long note on several topics gets one averaged vector, which lowers recall
  for each topic; and the agent puts up to 5 whole notes into the prompt, so context cost grows
  with note length. Add chunking (by heading, with the note title kept on each chunk) when the
  truncated flags or retrieval evals show it is needed.

## Docs

The contract is the `.proto` (see above). `docs/` will hold config, runbook and decisions
(embedding model choice first).
