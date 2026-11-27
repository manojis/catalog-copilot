# Evals

Offline checks of search quality against fixed datasets. Datasets are versioned in git; each run
writes a report to `evals/reports/`.

## Constraint satisfaction (M1)

**Question:** when a shopper states a hard limit ("under $100", "women's", "Nike", "black"), do the
returned products actually satisfy it? PRD target: **>= 95%** of returned products satisfy every
stated limit, and trap queries ("black friday", "boyfriend jeans") create **no** filter.

- Dataset: [`datasets/search_constraints.json`](datasets/search_constraints.json): 43 shopper
  queries. `expect` holds the limits a human reads in the query, written from intent and **not**
  from the parser's output (otherwise the check could never fail). `kind: "trap"` cases must create
  no filter. Includes phrasings the M1 rules are known to miss ("for him", "a hundred dollars").
- Code: `src/catalog_copilot/evals/constraints.py`.
- Run (needs the loaded local catalog):
  ```bash
  uv run catalog-copilot-eval-constraints      # prints the report, writes reports/search_constraints.json
  uv run pytest -m e2e                         # same check as a test (fails below target)
  ```
  The command exits non-zero below target, so it can gate CI later (M4).

**What it measures:** SQL enforces whatever the parser extracts, so violations come from parser
misses. This is effectively an end-to-end parser test on realistic phrasing; `parse_accuracy` is the
baseline the M2 LLM parser must beat.

**What it can't see:** products are checked against their stored attributes, so wrong attributes
from ingest (e.g. a mislabeled gender) are invisible here. That needs human relevance labels (M4).

### M1 baseline (2026-11-27, 30K catalog, BGE-small + MiniLM-L-6, limit 10)

| Metric | Result |
|---|---|
| Constraint satisfaction | **99.2%** (348 / 351 products) -> PASS |
| Parse accuracy | 95.3% (41 / 43 queries) |
| False filters on traps | 0 / 7 |
| Zero-result queries | none |
| Latency (full search) | p50 263 ms, p95 370 ms |

The only failures are the two expected rule-parser misses:
- "jacket for him under 100 bucks": "for him" isn't recognized as men's (8/10 still men's or unisex).
- "running shoes less than a hundred dollars": numbers in words aren't parsed (1 shoe at $139.95).
