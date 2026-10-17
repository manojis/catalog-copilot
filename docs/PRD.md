# PRD: catalog-copilot

_Last updated: 2026-10-17_

## Problem
Product catalogs are large, inconsistent, and slow to work with. Merchandisers and shoppers
can't find products with plain-language questions ("breathable running shoes for wide feet
under $100"). PIM teams spend hours turning messy supplier files into clean, structured,
correctly categorized records. Keyword search and manual data entry don't scale, and
naive LLM tools invent specs that aren't in the source data.

## Target user
- **Primary (v1):** merchandisers and catalog/PIM analysts working with an apparel catalog.
- **Secondary:** hiring managers and recruiters trying the live demo. The app must be usable in a
  browser with no setup, and the repo must clearly show production-grade AI engineering.

## V1 scope
**Must have**
- **Catalog search & Q&A:** ask natural-language questions about the catalog and get
  answers grounded in real products, with citations (product IDs/links) for every claim.
- **"I don't know" behavior:** if the catalog doesn't contain the answer, say so
  instead of inventing it.
- **Supplier attribute extraction:** upload a messy supplier CSV/PDF and get product
  records back in a fixed schema (brand, category, color, size, material, gender, price),
  with fields flagged as low-confidence or missing.
- **Taxonomy classification:** assign each product a Google Product Taxonomy category
  with a confidence score.
- **Simple web UI:** search/chat page plus an upload page, usable by non-engineers.
- **Guardrails:** resists prompt injection in user queries and uploaded files; rejects
  output that fails schema validation; never states specs that aren't in the source data.
- **Measured quality:** published eval scores (RAGAS + custom accuracy metrics)
  checked automatically on every change. Quality drops block the merge.
- **Live deployment:** a public URL that works.
- **Swappable LLM provider:** switch providers through config, not code changes.

**Should have** (build if cheap, else roadmap)
- Filters combined with search (price range, size, brand).
- Side-by-side eval comparison of two LLM providers in the README.
- Request tracing dashboard (LangSmith) linked from the README.

**Won't have in v1** (explicitly out)
- User accounts / auth, multi-tenant catalogs.
- Writing results back into a real PIM system (Akeneo, Salsify, etc.).
- Image understanding (product photos).
- Fine-tuning a model.
- Java/Spring Boot client (possible later phase).
- Product description generation (roadmap).

## Success criteria
- A first-time visitor can open the live URL and get a cited answer within 10 seconds.
- Golden eval set (50+ questions): faithfulness >= 0.85, answer relevancy >= 0.80;
  on out-of-catalog questions, correctly declines >= 90% of the time.
- Attribute extraction: >= 90% field-level accuracy on a labeled sample of 100 products.
- Taxonomy classification: >= 80% top-1 accuracy at taxonomy level 3 on a labeled sample.
- 100% of the prompt-injection test cases are blocked.
- Every PR that touches prompts, retrieval, or model config runs the eval gate and posts
  scores. A deliberately degraded prompt is caught and blocked (demonstrated once).
- Monthly running cost under ~$20.

## Decisions (resolved open questions, 2026-10-17)
- Catalog size for v1: a ~30K-product subset of Amazon Reviews 2023 Clothing/Shoes/Jewelry.
- Supplier test files: generated messy CSV/PDF files built from real records, so the
  correct answers are known.
- Taxonomy ground truth: ~150 hand-checked labels.

## Open questions
- None blocking v1.
