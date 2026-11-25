# Status: catalog-copilot

_Last updated: 2026-11-24. Update this file at the end of every milestone._

## Current phase
Phase 4: building M1 (step 2 of 6 done).

## Milestones
- [ ] M1 Catalog + hybrid search: **in progress**
- [ ] M2 RAG Q&A + web UI
- [ ] M3 CI/CD + live deploy (Fly.io)
- [ ] M4 Eval gate
- [ ] M5 Guardrails
- [ ] M6 Supplier extraction + taxonomy + final README

## How to run
See README Quick start: docker compose → alembic upgrade → ingest download + load → app.

## Decisions made along the way
- 2026-10-17: Dataset = Amazon Reviews 2023 Clothing/Shoes/Jewelry (~30K subset); no free Nordstrom catalog exists.
- 2026-10-17: Provider-agnostic LLM layer (LiteLLM); Claude default, OpenAI optional.
- 2026-10-17: Hosting = Fly.io (user chose it over free Render + Neon).
- 2026-10-17: Repo created by user as **public**, Apache-2.0, and kept public. Strict secrets hygiene (.env + GitHub Secrets only).
- 2026-10-17: Python 3.12 via uv (system Python is 3.9).
- 2026-10-20: Added a query-understanding step: hard limits (price, gender, brand, size,
  color) are parsed into SQL filters before retrieval; soft preferences stay in the semantic
  query. Rule-based parser in M1, LLM parser in M2, constraint eval cases in M4.

- 2026-11-21: M1 is built step by step, with a plain-English walkthrough after each step (user is
  learning from the build).
- 2026-11-21: Local Docker via Rancher Desktop (already installed). Postgres runs in a container;
  the app runs on the host in dev.
- 2026-11-21: Industry-standard tooling throughout. Schema via SQLAlchemy models + Alembic
  migrations (chosen over Liquibase: Python-native, model/migration drift check). Integration
  tests use testcontainers. Added `products.search_text` (single product string for BGE + reranker).
- 2026-11-24: Dataset size is a CLI option (`--limit`). Build and test at 30K; later scale run at
  1M locally with HNSW (migration 0002, `ef_search >= 100`, iterative scan on) and re-measure
  recall on real embeddings. Deployed size decided in M3 against the ~$20/month target.
  Measured on 2 vCPU Docker Postgres: exact vector scan 12 ms @30K, 117 ms @500K, 212 ms @1M;
  HNSW @1M ~6 ms but 26 min build, 1.95 GB index; strict filters under-fill without iterative scan.
- 2026-11-24: `shm_size: 2gb` in docker-compose (Docker's 64 MB default breaks parallel HNSW builds).
- 2026-11-24: Ingest = `download` (raw snapshot, first N usable records in file order) + `load`
  (clean, embed, idempotent upsert). Data notes: 47% of raw records lack a price (skipped);
  brand = `store`; gender from `details.Department`, falling back to category; color is listed for
  only ~5% of products, so it falls back to the first color word in the title; no per-variant size
  data, so the size filter is out of scope for M1. Prices below $1 are placeholders ($0.01)
  and are rejected. Coverage at 30K: brand 100%, gender 98%, color 15%, material 4%.

## M1 progress
- [x] Step 1: Postgres + pgvector (docker compose), `products` model, migration 0001, tests
- [x] Step 2: ingest 30K products (download, clean, embed, load): 29,990 loaded, 12.6 min
- [ ] Step 3: rule-based query parser + table-driven tests
- [ ] Step 4: keyword + vector retrieval, RRF, rerank
- [ ] Step 5: `GET /search`
- [ ] Step 6: end-to-end testing (incl. constraint satisfaction)

## Pending / blocked
- User accounts needed by M2/M3: Anthropic API key (prepaid credits), Fly.io account, LangSmith (free). OpenAI key optional.
