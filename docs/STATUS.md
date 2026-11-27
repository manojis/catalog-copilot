# Status: catalog-copilot

_Last updated: 2026-11-26. Update this file at the end of every milestone._

## Current phase
Phase 4: M1 built (all 6 steps); step 6 not yet merged. Next: M2 (after Augment/Generate lessons).

## Milestones
- [x] M1 Catalog + hybrid search: **built** (step 6 in review)
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
- 2026-11-26: Docs reorganized: detailed ingest docs moved from README to `docs/INGEST.md`;
  major decisions recorded as ADRs in `docs/adr/` (0001-0007); DESIGN/PRD corrected (no size
  filter, ingest command, measured scan latency).
- 2026-11-26: "Under $100" means `price < 100` (user decision). `ParsedQuery` records whether
  each price bound is inclusive. Brands are matched from the catalog, skipping names that other
  brands' titles use more often than the brand has products (197 of ~12.7K skipped at 30K).
- 2026-11-26: Gender filters are generous (user chose option A): women/men include unisex, kids
  includes girls and boys, girls/boys include kids. At 30K: "women" matches 18,549 products
  (17,368 women + 1,181 unisex), "kids" 2,809.
- 2026-11-26: Retrieval (step 4, details in DESIGN "Retrieval"): keyword search requires all words,
  then fills with any-word matches when fewer than 50; vector search is an exact scan; RRF merges by
  rank. The reranker reads the full `search_text` but only for the RRF top 30
  (`CC_RERANK_CANDIDATES`): all ~85 took ~780 ms, the top 30 ~240 ms. Filter-only queries list
  products cheapest first. A search takes 200-350 ms at 30K (reranker 170-320 ms of it).
- 2026-11-26: Commit messages carry the reasoning (Decisions + Measured sections), not just the change.
- 2026-11-26: `GET /search` (step 5): service built once at startup, fail fast if the database is
  unreachable; sync endpoint (blocking work runs in a worker thread); 422 for bad `q`/`limit`, 503 for
  database outages; app logging configured so each search logs its timings.
- 2026-11-27: M1 constraint check (step 6): 43 golden queries with limits written from intent;
  99.2% of returned products satisfy every stated limit (target 95%), parse accuracy 95.3%, 0 false
  filters on traps, p50 263 ms / p95 370 ms. Baseline for the M2 LLM parser. Runs as
  `catalog-copilot-eval-constraints` and `pytest -m e2e`.

## M1 progress
- [x] Step 1: Postgres + pgvector (docker compose), `products` model, migration 0001, tests
- [x] Step 2: ingest 30K products (download, clean, embed, load): 29,990 loaded, 12.6 min
- [x] Step 3: rule-based query parser + table-driven tests (PRs #3, #4)
- [x] Step 4: filters, keyword + vector retrieval, RRF, rerank, `search()` service (PR #5)
- [x] Step 5: `GET /search` (PR #6)
- [x] Step 6: end-to-end constraint check: 99.2% satisfaction (target 95%) (branch `feat/m1-e2e-constraints`)

### M1 pieces by side

"Ingest" runs once per product to fill the database; "Shopper" runs on every search.

| Step | Side | Piece | Status | What it does |
|---|---|---|---|---|
| 1 | Ingest | Postgres + pgvector container | done | Database that stores products, vectors and the keyword index |
| 1 | Ingest | `products` table (Alembic migration 0001) | done | Creates the table and its 4 indexes as a versioned migration |
| 2 | Ingest | download | done | Saves the first 30K usable raw records to a local snapshot file |
| 2 | Ingest | clean | done | Picks out brand, price, gender, color, material; builds `search_text` |
| 2 | Ingest | embed (`passage_embed`) | done | Turns each `search_text` into 384 numbers with BGE-small |
| 2 | Ingest | load (upsert, 256 per batch) | done | Writes products + vectors; re-running updates, never duplicates |
| 2 | Ingest | `search_tsv` (built by Postgres) | done | Postgres auto-builds keyword-search data from title, brand and text |
| 3 | Both | shared `vocabulary.py` | done | One gender/color list used by ingest and the parser, so values match |
| 3 | Shopper | query parser | done | Splits "women's black boots under $100" into filters + leftover text |
| 3 | Shopper | table-driven parser tests | done | One row per query, incl. traps like "Under Armour", "black friday" |
| 4 | Shopper | filters → SQL | done | Price (< vs <=), brand, generous gender, color as indexed WHERE conditions |
| 4 | Shopper | keyword search | done | Filtered full-text search on `search_tsv`: all words first, then any word, top 50 |
| 4 | Shopper | vector search (`query_embed`) | done | Embeds the leftover text and finds the 50 nearest filtered products |
| 4 | Shopper | RRF merge | done | Combines both ranked lists using rank positions only |
| 4 | Shopper | rerank (cross-encoder) | done | MiniLM rescores the RRF top 30 (full `search_text`) and keeps the best |
| 4 | Shopper | `search()` service | done | Runs the whole pipeline; per-stage timings; filter-only queries |
| 5 | Shopper | `GET /search?q=...` | done | The API the shopper calls; returns ranked products as JSON |
| 6 | Both | end-to-end tests | done | 43 golden queries on the real catalog: 99.2% of results satisfy every stated limit |
| Later | Ingest | full-refresh mode | later | Removes rows that a stricter cleaning rule now rejects |
| Later | Ingest | HNSW index (migration 0002) | later | Fast approximate vector search for the 1M scale run |
| Later | Ingest | 1M load + recall check | later | Measures HNSW vs exact search on real embeddings |

## Pending / blocked
- User accounts needed by M2/M3: Anthropic API key (prepaid credits), Fly.io account, LangSmith (free). OpenAI key optional.
