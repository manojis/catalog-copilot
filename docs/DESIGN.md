# Tech Design: catalog-copilot

_Last updated: 2026-11-26_

Major decisions and their reasoning are recorded as [Architecture Decision Records](adr/README.md).

## Stack
| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12, `uv` for deps | Industry standard for AI; uv is fast and reproducible |
| API | FastAPI + Pydantic v2 | Typed request/response models; free OpenAPI docs |
| LLM access | LiteLLM (default: Claude; second: OpenAI) | One interface across providers; provider chosen by config |
| Structured output | Pydantic schemas + `instructor` | Validated, typed LLM output for extraction/classification |
| Embeddings | `fastembed` (open-source BGE-small, local ONNX) | Free, no API key, fast on CPU; shows embedding-model knowledge |
| Storage + search | Postgres + `pgvector` + built-in full-text search | One boring database does vector search, keyword search, and records |
| DB access + migrations | SQLAlchemy 2.0 + psycopg 3; Alembic migrations | Standard Python data layer; versioned, reversible schema changes (Alembic ~ Flyway/Liquibase) |
| Query understanding | Rule-based parser (M1), then LLM structured output via `instructor` (M2) | Embeddings can't enforce "under $100"; hard limits become SQL filters |
| Hybrid ranking | Reciprocal Rank Fusion + cross-encoder reranker (fastembed) | Standard, explainable retrieval quality gains |
| PDF parsing | `pdfplumber` | Reliable text/table extraction from supplier PDFs |
| Web UI | Jinja2 templates + HTMX | Interactive pages with no JS build step |
| Evals | RAGAS + pytest + custom metrics; LangSmith datasets/experiments | Named in target job postings; numbers tracked in git |
| Tracing | LangSmith | Per-request traces; bad traces become new eval cases |
| Lint / types / tests | ruff, mypy, pytest; testcontainers for integration tests | Fast, standard; integration tests hit a real throwaway Postgres |
| CI/CD | GitHub Actions → Docker → GHCR → Fly.io (staging + prod) | Simple, cheap, real deployment pipeline |
| Local dev | docker compose (Postgres + pgvector); the app runs on the host in dev and is containerized in M3 | One command for the database; fast reload while developing |

## Architecture
```
                 +-------------------------- FastAPI app ---------------------------+
Browser (HTMX) ->| /search   -> parse_query -> retrieve -> rerank                   |-> ranked products
API clients    ->| /ask      -> guard_in -> parse_query -> retrieve -> rerank       |
                 |                         (filters +     (filtered  -> LLM answer  |
                 |                          semantic text) hybrid)    -> guard_out  |-> answer + citations
                 | /extract  -> parse CSV/PDF -> guard_in -> LLM (schema)           |
                 |              -> validate -> confidence flags                     |
                 | /classify -> embed -> top-k taxonomy nodes -> LLM pick           |
                 +-----+-------------------+-------------------+--------------------+
                       |                   |                   |
                Postgres+pgvector     LiteLLM -> Claude/OpenAI   LangSmith (traces)
                (products, taxonomy,
                 vectors, FTS index)

Offline: catalog-copilot-ingest download|load  (Amazon subset -> snapshot -> clean -> embed -> load;
         src/catalog_copilot/ingest/, see INGEST.md)
         scripts/make_supplier_files.py (real records -> messy CSV/PDF + answer keys)
         evals/  (golden datasets, RAGAS runner, baseline.json)
```
- **guard_in:** prompt-injection checks (heuristics + LLM classifier). Untrusted text
  (queries, file contents) is always clearly separated from instructions.
- **guard_out:** every citation must be a retrieved product ID. Every stated attribute
  must appear in the cited source; otherwise the answer is blocked or the claim removed.
  Answers are declined when retrieval confidence is low.

## Query understanding
Embeddings match meaning ("breathable" ~ "mesh upper") but not numbers or hard limits:
"under $100" only nudges a vector toward "cheap-ish" and never excludes a $140 shoe.
So each query is split before retrieval:
```
"breathable running shoes for wide feet under $100"
  -> ParsedQuery(semantic_text="breathable running shoes for wide feet",
                 price_max=100, price_max_inclusive=False)      # price < 100
```
- **Hard constraints -> SQL filters.** `price_min/price_max`, `gender`, `brand` and `color`
  become a `WHERE` clause applied to *both* the keyword and vector searches, so top-k is drawn
  only from products that qualify. The constraint text is removed from the semantic query.
  `size` is not filterable: the dataset has no per-variant sizes.
- **Only filter when confident** ([ADR 0007](adr/0007-rule-based-query-parser-in-m1.md)). A wrong
  hard filter hides products (possibly zero results); a wrong soft hint only reorders them. So
  ambiguous words ("black friday", "cheap") stay in the semantic query.
- **Rule order:** brands first (longest names first, so "Under Armour" isn't read as
  "under $100" and "New Balance" beats "Balance"), then price, gender, color; whole words only.
- **Price bounds say whether they include their value:** "under/below/less than $100" is
  `price < 100`; "up to/at most $100" is `<= 100`; "over $50" is `> 50`; "at least $50" and
  "$50+" are `>= 50`; "$50-$80" and "between 50 and 80" include both ends. A bare number counts
  only after "under/below/less than/between"; other phrases need "$" or "dollars", and numbers
  followed by a unit ("under 18 months") are never prices. Conflicting phrases create no filter.
- **Brands come from the catalog, minus everyday words.** The ~12.5K store names are loaded once
  at startup (~0.4 s). A name is skipped when other brands' titles use it more often than it has
  products of its own ("Comfort", "Polo", "Mini"), and placeholders like "Generic" are never
  brands. A matched brand also covers catalog brands that start with it ("adidas" also matches
  "adidas Originals"), because adding a related brand only adds results.
- **Shared vocabulary:** the query parser and ingest use the same gender and color values
  (e.g. "grey" -> `gray` on both sides), so query filters always match stored attributes.
- **Soft preferences -> ranking.** "breathable", "wide feet", "for hiking" stay in the
  semantic query and are handled by embeddings + reranker. (M2 may add LLM query rewriting
  into catalog vocabulary, e.g. "wide feet" -> "wide width 2E"; kept only if evals show a gain.)
- **M1: rule-based parser** (`query_parser.py`): regex for price phrases ("under $100",
  "$50-$80", "less than 100 dollars"), a gender word list, and brand matching against the
  distinct brands in the catalog. Deterministic, free, unit-tested.
- **M2: LLM parser** via `instructor` into a Pydantic `ParsedQuery` model; handles phrasing the
  rules miss ("nothing over a hundred bucks"). The rule parser stays as the fallback if the
  LLM call fails or times out.
- **Safety:** filters are Pydantic-validated (types, ranges, known enum values) and passed to
  SQL as bound parameters, never string-built, so a crafted query can't inject SQL.
- **Zero results after filtering:** say so plainly and show the nearest matches with the
  filter relaxed, labeled as such ("No running shoes under $100; closest: ... $109").
  Never silently drop the constraint.
- **Transparency:** the UI shows the applied filters as chips ("price <= $100") so users can
  see and remove a wrong interpretation.

## Data model
- **products:** `id` (ASIN), `title`, `brand`, `category_path`, `price`, `attributes` (JSONB:
  gender, color, material), `description`, `url`, `search_text` (the product string that BGE
  embeds and the reranker reads, [ADR 0004](adr/0004-search-text-column.md)),
  `embedding vector(384)`, `search_tsv tsvector` (generated by Postgres; title weighted highest)
- No vector index at ~30K rows: an exact scan takes ~12 ms in Postgres and never under-fills
  filtered results (see Scale plan).
- **taxonomy_nodes:** `id`, `path` ("Apparel & Accessories > Shoes > Athletic Shoes"),
  `level`, `embedding vector(384)`
- Filterable columns (`price`, `lower(brand)`, and JSONB `gender`/`color`) get B-tree / GIN
  indexes so filtered search stays fast.
- Schema changes go through Alembic migrations in `migrations/versions/`
  ([ADR 0002](adr/0002-alembic-migrations.md)).
- **Eval datasets (files, versioned in git):** `evals/datasets/{qa,extraction,taxonomy,guardrails}.jsonl`;
  scores in `evals/baseline.json`. QA cases with constraints carry an `expected_filters`
  field (see M4).

## Ingest
Details and diagrams: [INGEST.md](INGEST.md). Decision: [ADR 0005](adr/0005-two-stage-ingest.md).
- **Two stages.** `download` streams the dataset and saves the first N usable records unchanged
  (a reproducible snapshot in `data/`, git-ignored). `load` cleans, embeds and upserts from the
  snapshot, so cleaning changes don't need a new download.
- **Idempotent, batched load.** Batches of 256 are embedded and committed together
  (`INSERT ... ON CONFLICT DO UPDATE`); re-running updates rows instead of duplicating them.
- **Cleaning rules** (pure functions, table-driven tests): price in [$1, $10,000) ($0.01 values are
  placeholders); brand from `store`; gender from `details.Department`, falling back to the
  category; color from the listed color, falling back to the first color word in the title
  (listed for only ~5% of products); material when listed.
- **`search_text`** = title + `Brand:` + `Category:` + attributes + features (cut at 500 chars).
  Price is excluded (enforced by SQL, not embeddings).
- **One `Embedder`** for both sides: `passage_embed` for products, `query_embed` for queries,
  same model, so vectors are comparable.

## Scale plan
Dataset size is a CLI option (`--limit`). Build and test at 30K; a later local scale run at 1M.
Deployed size is chosen in M3 against the ~$20/month target.
[ADR 0006](adr/0006-exact-vector-scan-now-hnsw-at-scale.md) has the full measurements.

| Products | Exact vector scan (2 vCPU Postgres) | Ingest time (CPU embedding) |
|---|---|---|
| 30K | ~12 ms | ~13 min |
| 500K | ~117 ms | ~2.6 h (estimated) |
| 1M | ~212 ms | ~5 h (estimated) |

At 1M, migration 0002 adds an HNSW index (measured ~6 ms per query vs ~212 ms, but a 26-minute
build and a 1.95 GB index) with `hnsw.ef_search >= 100` (it must be at least the result limit) and
`hnsw.iterative_scan` on (without it, a filter keeping 1% of rows returned 0.5 of 50 results).
Recall is re-measured on real embeddings (random test vectors are not representative).

## External services / user action needed
- **Anthropic API key:** default LLM. Pay per use, expected a few $/month at portfolio volume.
- **OpenAI API key (optional):** second provider for the comparison eval. A few $/month.
- **LangSmith account:** free developer tier, gives an API key.
- **Fly.io account:** hosting for app + Postgres. Requires a credit card. Small apps
  cost roughly $0–10/month. (Alternative: Neon free tier for Postgres.)
- **GitHub repo secrets:** API keys added as Actions secrets (I'll walk you through it).
- **Dataset:** Amazon Reviews 2023 (McAuley Lab), free for research/non-commercial use.
  The README will credit it.
- Cost guardrails: per-PR evals capped at ~50 cases, LLM responses cached, daily spend
  limit set in each provider console.

## Milestones
Each milestone is independently runnable and demoable. Estimate: ~6-8 weeks at 10-20 hrs/week.
A live, cited-search demo exists after M3 (~3 weeks).

1. **Catalog + hybrid search.** Ingest the 30K apparel subset into Postgres/pgvector.
   `/search` returns ranked products using keyword + vector + RRF + reranker, with the
   rule-based query parser turning price/gender/brand/color phrases into SQL filters
   (table-driven unit tests). Runs via docker compose. No LLM yet.
2. **RAG Q&A + web UI.** `/ask` answers with citations through LiteLLM (provider switchable
   by config), with LangSmith tracing and an HTMX chat/search page. LLM query parser
   (rule parser as fallback); applied filters shown as removable chips.
3. **CI/CD + live deploy.** GitHub Actions: ruff, mypy, pytest (mocked LLM) → Docker → GHCR →
   Fly.io staging (smoke test) → prod with manual approval. Public URL works.
4. **Eval gate.** Golden QA set (50+ cases incl. out-of-catalog questions), RAGAS + custom
   metrics, `baseline.json`, PR-comment scores, merge blocked on regression, nightly full run.
   Demo: a deliberately degraded prompt gets blocked.
   The golden set includes 10-15 **constraint cases**: price limits and ranges ("under $100",
   "between $40 and $60"), gender, brand, combined limits ("women's Columbia jacket under
   $150"), a soft-vs-hard mix ("wide feet under $100"), and one with no qualifying product
   (must say so, not drop the limit). Two custom metrics:
   - *filter extraction accuracy*: parsed filters == `expected_filters` (no LLM judge needed)
   - *constraint satisfaction*: share of returned/cited products that meet every stated limit
     (target >= 95%)
5. **Guardrails.** Injection defenses, grounding/citation checks, declining low-confidence
   questions. A guardrail test suite runs in CI with a 100% pass requirement.
6. **Supplier extraction + taxonomy.** `/extract` (CSV/PDF → schema with confidence flags)
   and `/classify` (Google taxonomy), UI upload page, their eval sets added to the gate.
   Final README with architecture diagram and eval score tables (incl. Claude vs OpenAI).

## Risks / decisions deferred
- **Dataset license** is research/non-commercial. Fine for a portfolio, but it can't become a product as-is.
- **Fly.io free allowance** may change. Fallback: Render + Neon.
- **LLM-judged metrics (RAGAS) are noisy.** Regression threshold set after measuring
  run-to-run variance in M4, not guessed.
- **Exact model choices and pricing** confirmed at M2 against current provider docs.
- **Filtered vector search can under-fill top-k.** An HNSW index finds neighbors first and
  filters after, so a strict filter can leave fewer than k results (measured: 0.5 of 50 for a
  1% filter). At 30K rows an exact scan is used; when HNSW is added, `hnsw.iterative_scan` is
  turned on. Verified with the "rare filter" eval cases in M4.
- **Embedding throughput** (~40 products/s on CPU) makes a 1M load take hours. Options if needed:
  shorter `search_text`, length-sorted batches, more cores or a GPU.
- **The LLM query parser adds latency and cost** to every `/ask`. Use a small/fast model and
  cache by query text; measured against the 10-second first-answer target in M2.
- Java/Spring Boot client, description generation, image understanding → ROADMAP.
