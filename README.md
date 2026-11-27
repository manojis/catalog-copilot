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

### Search the catalog

```bash
curl -G http://127.0.0.1:8000/search \
  --data-urlencode "q=women's black running shoes under \$100" --data-urlencode "limit=3"
```
```jsonc
{
  "query": "women's black running shoes under $100",
  "parsed": { "price_max": "100", "price_max_inclusive": false,   // price < 100
              "gender": "women", "color": "black", "brands": [],
              "semantic_text": "running shoes", ... },
  "results": [
    { "id": "B0BBSBNPZ6", "title": "JCONGUW ... Running Shoes ...", "brand": "JCONGUW",
      "price": "33.99", "url": "https://www.amazon.com/dp/B0BBSBNPZ6",
      "attributes": { "color": "black", "gender": "unisex" },
      "rerank_score": 6.30, "keyword_rank": 1, "vector_rank": 1, "rrf_rank": 1 },
    ...
  ],
  "candidates": 68,
  "timings_ms": { "parse": 0.4, "keyword": 12.7, "embed": 4.0, "vector": 6.7, "rerank": 323.1, "total": 354.0, ... }
}
```
- `q`: 1-500 characters; `limit`: 1-50 (default 10). Invalid values return 422.
- Prices are strings (exact decimals, no float rounding).
- Each result shows where it ranked in keyword search, vector search and RRF, plus the reranker's
  score (`null` ranks = that search didn't find it; filter-only queries like "Nike" have no scores).
- 503 means the database is unreachable. Interactive docs: http://127.0.0.1:8000/docs

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

### Ingest in short

`download` streams the dataset and saves the first N usable products unchanged to `data/raw/`
(a reproducible snapshot). `load` reads that file, cleans each record, builds one labeled
product string (`search_text`), embeds it with BGE-small, and inserts-or-updates the products in
Postgres in batches of 256. Postgres builds the keyword index (`search_tsv`) itself.

Step-by-step diagrams, the role of each file, a real stored product and data quality notes:
**[docs/INGEST.md](docs/INGEST.md)**.

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest              # unit + integration (integration starts a throwaway Postgres container)
uv run pytest -m "not integration and not e2e"   # unit tests only, no Docker needed
uv run pytest -m e2e       # end-to-end check on the loaded local catalog with the real models
uv run catalog-copilot-eval-constraints   # constraint-satisfaction report (see evals/README.md)
```
A command-line `-m` replaces the default `-m 'not e2e'`, so name `e2e` explicitly when filtering.

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
  vocabulary.py             gender/color values shared by ingest and the query parser
  db/                       SQLAlchemy models and sessions
  ingest/                   download + load pipeline
  search/                   query parser, filters, keyword/vector retrieval, RRF, rerank, service
  evals/                    offline evaluations (constraint satisfaction)
migrations/versions/        Alembic migrations (0001: products table)
tests/unit/                 fast tests, no Docker (table-driven where rules have many cases)
tests/integration/          tests against a throwaway Postgres container (testcontainers)
tests/e2e/                  checks on the loaded local catalog with real models (pytest -m e2e)
evals/                      golden datasets and reports (see evals/README.md)
data/raw/                   downloaded snapshots (git-ignored)
docs/                       PRD, DESIGN, STATUS, INGEST, adr/ (architecture decision records)
```

## Docs
- [Product requirements](docs/PRD.md)
- [Technical design](docs/DESIGN.md)
- [Status](docs/STATUS.md)
- [Ingest](docs/INGEST.md)
- [Architecture decision records](docs/adr/README.md)
- [Evals](evals/README.md)

## Data
Product data from [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/) (McAuley Lab),
used for non-commercial research/demo purposes.

## License
Apache-2.0
