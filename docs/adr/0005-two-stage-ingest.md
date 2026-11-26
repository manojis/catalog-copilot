# 0005: Two-stage ingest: raw snapshot, then idempotent load

- **Status:** Accepted
- **Date:** 2026-11-24

## Context
The source file (Amazon Reviews 2023, Clothing/Shoes/Jewelry metadata) is 18 GB. Only ~53% of
records have a usable price. Cleaning rules will change as data problems are found (e.g. $0.01
placeholder prices), and embedding is slow (~40 products/s on CPU), so ingest gets re-run often
and may fail partway through a long run.

## Decision
Ingest is a CLI with two commands (`catalog-copilot-ingest`):
- `download --limit N` streams the file, keeps the first N usable records **unchanged**, and writes
  them to `data/raw/clothing_<N>.jsonl.gz` (git-ignored). A `.partial` file is renamed only when
  complete.
- `load --limit N` reads the snapshot, cleans each record, embeds `search_text` in batches of 256,
  and upserts each batch in its own transaction (`INSERT ... ON CONFLICT (id) DO UPDATE`).

## Consequences
- A cleaning change needs only a re-`load`; the snapshot makes loads reproducible.
- Re-running `load` updates rows in place; a crash loses at most one batch.
- Records removed by a stricter rule are not deleted by a re-load (upsert never deletes). Today this
  was handled by a one-off delete; a full-refresh mode is needed before automated reloads.
- "First N usable records in file order" is not a random sample. Fine for development; revisit if
  category balance matters for evals.
