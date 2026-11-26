# catalog-copilot

LLM-powered product catalog assistant for PIM: RAG search with citations, supplier attribute
extraction, and taxonomy classification. Provider-agnostic, with RAGAS/LangSmith evals and
guardrails enforced in CI/CD.

> Status: early development. See [docs/STATUS.md](docs/STATUS.md).

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Docker (Docker Desktop, Rancher Desktop, or similar).

```bash
uv sync                    # install Python 3.12 + dependencies
cp .env.example .env
docker compose up -d       # Postgres 17 + pgvector on localhost:5432
uv run alembic upgrade head   # create/upgrade the database schema
uv run catalog-copilot-ingest download --limit 30000   # raw snapshot -> data/raw/ (~10 s)
uv run catalog-copilot-ingest load --limit 30000       # clean + embed + load (~10 min on CPU)
uv run catalog-copilot     # http://127.0.0.1:8000/health  (API docs at /docs)
```

Use `--limit` for other sizes (e.g. `1000000` for a scale run). To browse the data, connect any
Postgres client to host `localhost`, port `5432`, database/user/password `catalog` (local dev only).

## How it works

The system has two sides. **Ingest** prepares the products once; **search** answers each shopper
query. Both use the same embedding model, so product vectors and query vectors are comparable.

```
 INGEST (offline, once)                          SEARCH (every request)        [M1: in progress]
 ──────────────────────                          ──────────────────────
 Amazon dataset (18 GB, streamed)                "women's black running shoes under $100"
        │ download                                      │ parse_query
        ▼                                               ├─ filters: gender=women, color=black,
 data/raw/clothing_30000.jsonl.gz                       │           price<=100   → SQL WHERE
        │ load: clean → search_text → embed              └─ semantic_text: "running shoes"
        ▼                                                       │
 Postgres `products` ───────────────────────────────►  keyword search (search_tsv)  ┐
   search_text   (the product string)                   vector search (embedding)    ├→ RRF → rerank
   embedding     (384 numbers, BGE-small)                                            ┘      │
   search_tsv    (keyword index, built by Postgres)                                         ▼
   price / brand / attributes (filter columns)                                    top results (/search)
```

### Ingest, step by step

Ingest is two commands, so a cleaning change only needs a re-`load`, not a new download. The
snapshot is a frozen copy of the input, which makes every load reproducible.

#### Command 1: `catalog-copilot-ingest download --limit 30000`

Goal: get 30K usable products from the internet into a local file.

```
 ┌─ cli.py ──────────────────────────────────────────────────────────┐
 │ reads the command ("download", limit 30000) and starts the work   │
 └──────────────────────────────┬────────────────────────────────────┘
                                ▼
 ┌─ pipeline.py (download_snapshot) ─────────────────────────────────┐
 │ runs the download loop                                            │
 │                                                                   │
 │   source.py   streams the 18 GB Amazon file from Hugging Face,    │
 │               one product record at a time                        │
 │        │                                                          │
 │        ▼                                                          │
 │   clean.py    checks each record: "is this usable?"               │
 │               (has an id, a title, and a price of $1 or more)     │
 │        │                                                          │
 │        ├─ not usable → skip it, count the reason                  │
 │        └─ usable     → write the record UNCHANGED to the file     │
 │                                                                   │
 │   stop once 30,000 usable records are saved                       │
 └──────────────────────────────┬────────────────────────────────────┘
                                ▼
           data/raw/clothing_30000.jsonl.gz   (22 MB, local, git-ignored)
```

Result: 56,543 records read, 30,000 kept, 26,543 skipped (no price), in about 7 seconds. The file is
filtered only to pick usable records; the data inside is still raw.

#### Command 2: `catalog-copilot-ingest load --limit 30000`

Goal: read that local file, clean it, embed it, and insert it into Postgres.

```
 ┌─ cli.py ──────────────────────────────────────────────────────────┐
 │ reads the command ("load") and starts the work                    │
 │ loads the BGE model once (embeddings.py)                          │
 └──────────────────────────────┬────────────────────────────────────┘
                                ▼
 ┌─ pipeline.py (load_products) ─────────────────────────────────────┐
 │                                                                   │
 │ ① source.py     READS the downloaded file                         │
 │                 data/raw/clothing_30000.jsonl.gz, one record at   │
 │                 a time                                            │
 │        ▼                                                          │
 │ ② clean.py      CLEANS each record:                               │
 │                 price → 99.95   brand → ASICS   gender → women    │
 │                 color → black   category → Women > Shoes > ...    │
 │                 and builds search_text                            │
 │        ▼                                                          │
 │ ③ pipeline.py   groups the clean products into batches of 256     │
 │        ▼                                                          │
 │ ④ embeddings.py EMBEDS each batch's search_text with BGE          │
 │                 → 384 numbers per product                         │
 │        ▼                                                          │
 │ ⑤ pipeline.py   INSERTS the batch into the products table         │
 │                 (if a product already exists, it's updated        │
 │                  instead of duplicated)                           │
 │        │                                                          │
 │        │  uses: db/session.py  → the connection to Postgres       │
 │        │        config.py      → the database address             │
 │        │        db/models.py   → what the products table looks    │
 │        │                         like                             │
 │        ▼                                                          │
 │   repeat ①–⑤ until the file is finished                           │
 └──────────────────────────────┬────────────────────────────────────┘
                                ▼
 ┌─ Postgres (in Docker) ────────────────────────────────────────────┐
 │ products table: one row per product, with search_text + embedding │
 │ Postgres fills in search_tsv (keyword data) by itself             │
 └───────────────────────────────────────────────────────────────────┘
```

Result: about 13 minutes for 30,000 products on a laptop CPU; almost all of it is step ④, embedding.
Because inserts are idempotent, re-running `load` updates rows in place instead of duplicating them.

#### Each file's job in one line

| File (`src/catalog_copilot/`) | Job |
|---|---|
| `ingest/cli.py` | the command you type; decides whether to download or load |
| `ingest/pipeline.py` | runs the steps in order: the "manager" |
| `ingest/source.py` | reads records: from the internet (download) or from the local file (load) |
| `ingest/clean.py` | checks and cleans each record, and builds `search_text` |
| `embeddings.py` | turns `search_text` into 384 numbers with BGE (`embed_query` serves search later) |
| `db/models.py` | describes the `products` table (schema changes go through Alembic) |
| `db/session.py` + `config.py` | connect to Postgres (settings come from `CC_*` environment variables) |

### What a stored product looks like

`clean.py` turns a raw record into one labeled **product string**, `search_text`. This exact text is
what BGE embeds and what the reranker reads:

```
ASICS Women's GT-2000 9 Running Shoes. Brand: ASICS. Category: Women > Shoes > Athletic >
Running > Road Running. Gender: women. Features: Synthetic-and-mesh Imported Rubber sole ...
```

Price is deliberately **not** in `search_text`: numbers are enforced by SQL filters, not embeddings.
Features are cut at 500 characters (longer text embeds slower for little extra meaning).

| Column | Filled by | Used for |
|---|---|---|
| `search_text` | ingest | the reranker reads it; debugging what was embedded |
| `embedding` `vector(384)` | ingest (BGE-small, `passage_embed`) | vector search: matches meaning ("breathable" ≈ "mesh") |
| `search_tsv` `tsvector` | **Postgres** (generated column: title weight A, brand B, `search_text` C) | keyword search: exact words ("wide", "2E", brand names), GIN index |
| `price`, `brand`, `attributes` (JSONB: gender, color, material) | ingest | hard filters from the query parser |

There is no vector index at this size: an exact scan over 30K vectors takes ~12 ms. HNSW is planned
for the 1M scale run (measured: ~6 ms vs ~212 ms at 1M, but a 26-minute build and approximate
results). See [docs/STATUS.md](docs/STATUS.md) for the measurements.

### Data quality notes
- 47% of raw records have no price and are skipped; prices below $1 are placeholders and rejected.
- Coverage at 30K: brand 100% (from `store`), gender 98%, color 15% (listed or read from the
  title), material 4%. The dataset has no per-variant sizes, so there is no size filter.

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest              # integration tests start a throwaway Postgres container
uv run pytest -m "not integration"   # unit tests only, no Docker needed
```

### Database schema changes

The schema is managed with [Alembic](https://alembic.sqlalchemy.org/) migrations in
`migrations/versions/`. Models live in `src/catalog_copilot/db/models.py`.

```bash
# 1. edit the model, then generate a migration and review it by hand
uv run alembic revision --autogenerate --rev-id 0002 -m "describe the change"
uv run alembic upgrade head      # apply
uv run alembic downgrade -1      # roll back the last migration
uv run alembic check             # fails if models and migrations have drifted
```

### Project layout

```
src/catalog_copilot/
  main.py, config.py        FastAPI app and settings
  embeddings.py             BGE-small embeddings (shared by ingest and search)
  db/                       SQLAlchemy models and sessions
  ingest/                   download + load pipeline
migrations/versions/        Alembic migrations (0001: products table)
tests/unit/                 fast tests, no Docker (table-driven where rules have many cases)
tests/integration/          tests against a throwaway Postgres container (testcontainers)
data/raw/                   downloaded snapshots (git-ignored)
```

## Docs
- [Product requirements](docs/PRD.md)
- [Technical design](docs/DESIGN.md)
- [Status](docs/STATUS.md)

## Data
Product data from [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/) (McAuley Lab),
used for non-commercial research/demo purposes.

## License
Apache-2.0
