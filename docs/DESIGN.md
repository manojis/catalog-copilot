# Tech Design: catalog-copilot

_Last updated: 2026-10-17_

## Stack
| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12, `uv` for deps | Industry standard for AI; uv is fast and reproducible |
| API | FastAPI + Pydantic v2 | Typed request/response models; free OpenAPI docs |
| LLM access | LiteLLM (default: Claude; second: OpenAI) | One interface across providers; provider chosen by config |
| Structured output | Pydantic schemas + `instructor` | Validated, typed LLM output for extraction/classification |
| Embeddings | `fastembed` (open-source BGE-small, local ONNX) | Free, no API key, fast on CPU; shows embedding-model knowledge |
| Storage + search | Postgres + `pgvector` + built-in full-text search | One boring database does vector search, keyword search, and records |
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
                 +--------------------- FastAPI app ----------------------+
Browser (HTMX) ->| /ask      -> guard_in -> retrieve -> rerank -> LLM answer |
API clients   ->|                          (hybrid)            -> guard_out|-> answer + citations
                 | /extract  -> parse CSV/PDF -> guard_in -> LLM (schema)  |
                 |              -> validate -> confidence flags            |
                 | /classify -> embed -> top-k taxonomy nodes -> LLM pick  |
                 +-----+-------------------+-------------------+-----------+
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

## Data model
- **products:** `id` (ASIN), `title`, `brand`, `category_path`, `price`, `attributes` (JSONB:
  color, size, material, gender...), `description`, `url`, `embedding vector(384)`,
  `search_tsv tsvector`
- **taxonomy_nodes:** `id`, `path` ("Apparel & Accessories > Shoes > Athletic Shoes"),
  `level`, `embedding vector(384)`
- **Eval datasets (files, versioned in git):** `evals/datasets/{qa,extraction,taxonomy,guardrails}.jsonl`;
  scores in `evals/baseline.json`

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
   `/search` returns ranked products using keyword + vector + RRF + reranker. Runs via docker compose. No LLM yet.
2. **RAG Q&A + web UI.** `/ask` answers with citations through LiteLLM (provider switchable
   by config), with LangSmith tracing and an HTMX chat/search page.
3. **CI/CD + live deploy.** GitHub Actions: ruff, mypy, pytest (mocked LLM) → Docker → GHCR →
   Fly.io staging (smoke test) → prod with manual approval. Public URL works.
4. **Eval gate.** Golden QA set (50+ cases incl. out-of-catalog questions), RAGAS + custom
   metrics, `baseline.json`, PR-comment scores, merge blocked on regression, nightly full run.
   Demo: a deliberately degraded prompt gets blocked.
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
- Java/Spring Boot client, description generation, image understanding → ROADMAP.
