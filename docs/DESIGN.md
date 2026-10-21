# Tech Design: catalog-copilot

_Last updated: 2026-10-20_

## Stack
| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12, `uv` for deps | Industry standard for AI; uv is fast and reproducible |
| API | FastAPI + Pydantic v2 | Typed request/response models; free OpenAPI docs |
| LLM access | LiteLLM (default: Claude; second: OpenAI) | One interface across providers; provider chosen by config |
| Structured output | Pydantic schemas + `instructor` | Validated, typed LLM output for extraction/classification |
| Embeddings | `fastembed` (open-source BGE-small, local ONNX) | Free, no API key, fast on CPU; shows embedding-model knowledge |
| Storage + search | Postgres + `pgvector` + built-in full-text search | One boring database does vector search, keyword search, and records |
| Query understanding | Rule-based parser (M1), then LLM structured output via `instructor` (M2) | Embeddings can't enforce "under $100"; hard limits become SQL filters |
| Hybrid ranking | Reciprocal Rank Fusion + cross-encoder reranker (fastembed) | Standard, explainable retrieval quality gains |
| PDF parsing | `pdfplumber` | Reliable text/table extraction from supplier PDFs |
| Web UI | Jinja2 templates + HTMX | Interactive pages with no JS build step |
| Evals | RAGAS + pytest + custom metrics; LangSmith datasets/experiments | Named in target job postings; numbers tracked in git |
| Tracing | LangSmith | Per-request traces; bad traces become new eval cases |
| Lint / types / tests | ruff, mypy, pytest | Fast, standard |
| CI/CD | GitHub Actions → Docker → GHCR → Fly.io (staging + prod) | Simple, cheap, real deployment pipeline |
| Local dev | docker compose (app + Postgres) | One command to run everything |

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

Offline: scripts/ingest.py  (Amazon subset -> clean -> embed -> load)
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
  -> { "semantic_query": "breathable running shoes for wide feet",
       "filters": { "price_max": 100 } }
```
- **Hard constraints -> SQL filters.** `price_min/price_max`, `gender`, `brand`, `size`,
  `color` become a `WHERE` clause applied to *both* the keyword and vector searches, so
  top-k is drawn only from products that qualify. The constraint text is removed from the
  semantic query.
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
  color, size, material, gender...), `description`, `url`, `embedding vector(384)`,
  `search_tsv tsvector`
- **taxonomy_nodes:** `id`, `path` ("Apparel & Accessories > Shoes > Athletic Shoes"),
  `level`, `embedding vector(384)`
- Filterable columns (`price`, `brand`, and JSONB `gender`/`size`/`color`) get B-tree / GIN
  indexes so filtered vector search stays fast.
- **Eval datasets (files, versioned in git):** `evals/datasets/{qa,extraction,taxonomy,guardrails}.jsonl`;
  scores in `evals/baseline.json`. QA cases with constraints carry an `expected_filters`
  field (see M4).

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
   rule-based query parser turning price/gender/brand phrases into SQL filters
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
  filters after, so a strict filter can leave fewer than k results. At 30K rows an exact
  (non-index) scan is cheap enough; if an index is added, use pgvector's iterative index
  scan setting. Verified with the "rare filter" eval cases in M4.
- **The LLM query parser adds latency and cost** to every `/ask`. Use a small/fast model and
  cache by query text; measured against the 10-second first-answer target in M2.
- Java/Spring Boot client, description generation, image understanding → ROADMAP.
