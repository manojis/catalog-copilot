# 0007: Rule-based query parser in M1; hard filters only when confident

- **Status:** Accepted (implemented in M1 step 3)
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
  (`brands`, `price_min`, `price_min_inclusive`, `price_max`, `price_max_inclusive`, `gender`,
  `color`, `semantic_text`). Validation rejects negative prices, min > max, empty ranges and
  gender/color values outside the fixed vocabularies.
- "Under $100" means `price < 100` (decided 2026-11-26), so each bound records whether it includes
  its value: "under/below/less than" and "over/above/more than" are exclusive, "up to/at most",
  "at least/$50+" and ranges ("$50-$80", "between 50 and 80") are inclusive.
- Rules run in this order: brands (from the catalog's own brand list, longest names first, skipping
  brand names that are everyday words), price phrases, gender words, colors. Whole words only.
- "Everyday word" is measured on the catalog: a brand name is skipped when other brands' titles
  use it more often than that brand has products (at 30K: 197 of ~12.7K names, e.g. "Comfort"
  2 products vs 453 other titles; "Nike" 97 vs 0). A matched brand also covers catalog brands that
  start with it ("adidas" -> "adidas Originals"); adding a related brand only adds results.
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
- A brand that is also a common name can still be misread ("Bruce Lee t-shirt" -> brand Lee).
  The LLM parser in M2 is measured against these cases.
- Building the brand list scans every title (~0.4 s at 30K, roughly linear); at 1M it should be
  cached or precomputed at ingest.
- No size filter: the dataset has no per-variant sizes.
