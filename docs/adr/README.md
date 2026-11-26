# Architecture Decision Records

Each record explains one significant decision: the context, what was decided, and the
consequences. Records are never rewritten after acceptance; a later record supersedes an earlier
one instead. Format: [Michael Nygard's ADR template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

| # | Decision | Status | Date |
|---|---|---|---|
| [0001](0001-postgres-pgvector-single-store.md) | One Postgres database for records, keyword and vector search | Accepted | 2026-10-17 |
| [0002](0002-alembic-migrations.md) | Versioned schema with SQLAlchemy models and Alembic (not a schema.sql, not Liquibase) | Accepted | 2026-11-21 |
| [0003](0003-docker-postgres-and-testcontainers.md) | Postgres in Docker for dev; integration tests on throwaway containers | Accepted | 2026-11-21 |
| [0004](0004-search-text-column.md) | Store one labeled product string (`search_text`) for the embedder and the reranker | Accepted | 2026-11-21 |
| [0005](0005-two-stage-ingest.md) | Two-stage ingest: raw snapshot, then idempotent load | Accepted | 2026-11-24 |
| [0006](0006-exact-vector-scan-now-hnsw-at-scale.md) | Exact vector scan at 30K; HNSW for the 1M scale run | Accepted | 2026-11-24 |
| [0007](0007-rule-based-query-parser-in-m1.md) | Rule-based query parser in M1; hard filters only when confident | Accepted | 2026-11-26 |

New record: copy the most recent file, use the next number, and add a row here.
