# 0001: One Postgres database for records, keyword and vector search

- **Status:** Accepted
- **Date:** 2026-10-17

## Context
Search needs three things: product records with filterable fields (price, brand, gender, color),
keyword search for exact tokens (brand names, "2E"), and vector search for meaning. Common setups
split these across a relational database, a search engine (Elasticsearch/OpenSearch) and a vector
database (Pinecone, Qdrant, Milvus). The catalog is ~30K products, possibly 1M for a scale run, and
the hosting budget is about $20/month.

## Decision
Use a single Postgres 17 database with the pgvector extension:
- records and filters in ordinary columns and JSONB, with B-tree/GIN indexes;
- keyword search with Postgres full-text search (a generated `tsvector` column and a GIN index);
- vector search with pgvector (`vector(384)`, cosine distance `<=>`).

## Consequences
- One service to run, back up and deploy; filters, keyword and vector search can share one SQL
  query, so hard filters apply to both retrievers before top-k.
- Postgres full-text ranking is simpler than a BM25 engine (scores saturate; see INGEST.md).
  Acceptable at this size; revisit if keyword quality limits the eval scores.
- Scaling to hundreds of millions of products would need a dedicated search engine or sharding.
  Out of scope for this project.
