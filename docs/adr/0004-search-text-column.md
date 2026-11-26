# 0004: Store one labeled product string (`search_text`)

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
Two models read product text: BGE-small embeds it at ingest, and the cross-encoder reranker reads
it at search time. If each built its own text from the raw fields, they could see different
descriptions, and nobody could easily tell what was embedded when debugging a bad result.
A reranker experiment showed labels matter: a product scored -7.17 from its title alone and +6.02
once "Category: Running Shoes" was included.

## Decision
`clean.py` builds one string per product and stores it in `products.search_text`:
title + `Brand:` + `Category:` + attributes (`Gender:`, `Color:`, `Material:`) + `Features:`
(cut at 500 characters on a word boundary). Price is excluded: it is enforced by SQL filters, and
numbers don't help embeddings. The same column feeds the embedder, the reranker and (with title and
brand) the generated keyword column.

## Consequences
- Embedder and reranker always see identical text; what was embedded is inspectable in SQL.
- Changing the format means re-running `load` (about 13 minutes at 30K) to re-embed.
- Feature lists are joined with spaces, which blurs boundaries between features; a separator may
  read better. To be measured once search evals exist, not changed blindly.
