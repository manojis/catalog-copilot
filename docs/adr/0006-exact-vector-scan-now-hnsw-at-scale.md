# 0006: Exact vector scan at 30K; HNSW for the 1M scale run

- **Status:** Accepted
- **Date:** 2026-11-24

## Context
The user asked to consider 500K or 1M products instead of 30K. pgvector offers exact search (scan
every vector) or approximate indexes (HNSW, IVFFlat). Approximate indexes are faster but can miss
results, take time and memory to build, and under-fill results when combined with strict filters.

Measured on Docker Postgres with 2 vCPUs / 6 GB, "nearest 50" query, median of 5 runs:

| Products | Exact scan | Exact + `price <= 100` |
|---|---|---|
| 30K | ~12 ms | ~9 ms |
| 500K | ~117 ms | ~107 ms |
| 1M | ~212 ms | ~183 ms |

HNSW at 1M (`m=16, ef_construction=64`): ~6 ms per query (ef_search 40), 26 minutes to build,
1.95 GB index. With ef_search 40 and no iterative scan, a filter keeping 50% of rows returned
20.6 of 50 results and a 1% filter returned 0.5 of 50; with `hnsw.iterative_scan = relaxed_order`
both returned 50 (19 ms and 106 ms). Recall measured on random vectors was 13-17%, which says more
about random data (all points nearly equidistant) than about HNSW; it must be measured on real
embeddings.

## Decision
- Dataset size is a CLI option (`--limit`). Develop and test at 30K with **no vector index**:
  exact, nothing to tune, never under-fills filtered results.
- For the 1M local scale run, add HNSW in migration 0002 with `hnsw.ef_search >= 100` (it must be
  at least the result limit) and `hnsw.iterative_scan` on, then measure recall against exact
  search on real BGE embeddings.
- Choose the deployed catalog size in M3 against the ~$20/month hosting target.

## Consequences
- Fast iteration now (a full re-load is ~13 minutes instead of ~5 hours).
- At 1M, exact search still answers in ~0.2 s but uses every DB core per query (~5 queries/s), so
  HNSW is needed for capacity, not single-user latency.
- Benchmarks must disable psycopg's automatic prepared statements (`prepare_threshold=None`) when
  comparing settings, or cached plans silently measure the wrong thing.
