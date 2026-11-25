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

Ingest is two stages: `download` streams the dataset and saves the first N usable products
unchanged (a reproducible raw snapshot); `load` cleans them, embeds `search_text` with
BGE-small, and upserts into Postgres. `load` is idempotent, so re-running it after changing a
cleaning rule updates rows in place. Use `--limit` for other sizes (e.g. 1000000 for a scale run).

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

## Docs
- [Product requirements](docs/PRD.md)
- [Technical design](docs/DESIGN.md)
- [Status](docs/STATUS.md)

## Data
Product data from [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/) (McAuley Lab),
used for non-commercial research/demo purposes.

## License
Apache-2.0
