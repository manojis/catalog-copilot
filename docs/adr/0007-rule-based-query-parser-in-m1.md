# 0007: Rule-based query parser in M1; hard filters only when confident

- **Status:** Accepted (implementation is M1 step 3)
- **Date:** 2026-11-26

## Context
Embeddings can't enforce limits: "under $100" only nudges a vector toward cheap-sounding products,
so a $140 shoe can still rank first. Limits stated in the query must become SQL filters. An LLM
can parse varied phrasing, but adds cost, latency and a provider dependency, and M1 has no LLM.

Parser mistakes are asymmetric. A wrong hard filter **hides** products (e.g. "black friday white
sneakers" read as `color = black` returns nothing, and the shopper can't tell why). A wrong soft
hint only **reorders** results.

## Decision
- M1 uses a deterministic rule parser returning a validated Pydantic `ParsedQuery`
  (`price_min`, `price_max`, `gender`, `color`, `brands`, `semantic_text`). Validation rejects
  negative prices, min > max, and gender/color values outside the fixed vocabularies.
- Rules run in this order: brands (from the catalog's own brand list, longest names first, skipping
  brand names that are everyday words), price phrases, gender words, colors. Whole words only.
  Matched text is removed; the remainder is `semantic_text` for keyword and vector search.
- Gender and color vocabularies are shared with ingest, so query values match stored attributes.
- When a match is ambiguous, no filter is created and the words stay in `semantic_text`.
- Behavior is pinned by table-driven unit tests (one row per query, including traps such as
  "Under Armour", "men" inside "women", "black friday", "cheap").
- M2 adds an LLM parser that fills the same `ParsedQuery`; the rule parser stays as its fallback.

## Consequences
- Free, fast and testable; filter extraction accuracy becomes the M1 baseline for M2's LLM parser.
- Phrasing the rules don't cover ("a hundred bucks", "not leather") falls through as soft text
  until M2.
- No size filter: the dataset has no per-variant sizes.
