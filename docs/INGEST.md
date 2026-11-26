# Ingest: how products get into the database

Ingest prepares the **products** once, before anyone searches. It is separate from the search
side (query parser, retrieval, `/search`). Design decisions behind it are recorded in
[DESIGN.md](DESIGN.md#ingest) and the [ADRs](adr/README.md).

```bash
uv run catalog-copilot-ingest download --limit 30000   # raw snapshot -> data/raw/
uv run catalog-copilot-ingest load --limit 30000       # clean + embed + upsert into Postgres
```

Ingest is two commands, so a cleaning change only needs a re-`load`, not a new download. The
snapshot is a frozen copy of the input, which makes every load reproducible.

## Command 1: `catalog-copilot-ingest download --limit 30000`

Goal: get 30K usable products from the internet into a local file.

```
 ┌─ cli.py ──────────────────────────────────────────────────────────┐
 │ reads the command ("download", limit 30000) and starts the work   │
 └──────────────────────────────┬────────────────────────────────────┘
                                ▼
 ┌─ pipeline.py (download_snapshot) ─────────────────────────────────┐
 │ runs the download loop                                            │
 │                                                                   │
 │   source.py   streams the 18 GB Amazon file from Hugging Face,    │
 │               one product record at a time                        │
 │        │                                                          │
 │        ▼                                                          │
 │   clean.py    checks each record: "is this usable?"               │
 │               (has an id, a title, and a price of $1 or more)     │
 │        │                                                          │
 │        ├─ not usable → skip it, count the reason                  │
 │        └─ usable     → write the record UNCHANGED to the file     │
 │                                                                   │
 │   stop once 30,000 usable records are saved                       │
 └──────────────────────────────┬────────────────────────────────────┘
                                ▼
           data/raw/clothing_30000.jsonl.gz   (22 MB, local, git-ignored)
```

Result: 56,543 records read, 30,000 kept, 26,543 skipped (no price), in about 7 seconds. The file is
filtered only to pick usable records; the data inside is still raw.

## Command 2: `catalog-copilot-ingest load --limit 30000`

Goal: read that local file, clean it, embed it, and insert it into Postgres.

```
 ┌─ cli.py ──────────────────────────────────────────────────────────┐
 │ reads the command ("load") and starts the work                    │
 │ loads the BGE model once (embeddings.py)                          │
 └──────────────────────────────┬────────────────────────────────────┘
                                ▼
 ┌─ pipeline.py (load_products) ─────────────────────────────────────┐
 │                                                                   │
 │ ① source.py     READS the downloaded file                         │
 │                 data/raw/clothing_30000.jsonl.gz, one record at   │
 │                 a time                                            │
 │        ▼                                                          │
 │ ② clean.py      CLEANS each record:                               │
 │                 price → 99.95   brand → ASICS   gender → women    │
 │                 color → black   category → Women > Shoes > ...    │
 │                 and builds search_text                            │
 │        ▼                                                          │
 │ ③ pipeline.py   groups the clean products into batches of 256     │
 │        ▼                                                          │
 │ ④ embeddings.py EMBEDS each batch's search_text with BGE          │
 │                 → 384 numbers per product                         │
 │        ▼                                                          │
 │ ⑤ pipeline.py   INSERTS the batch into the products table         │
 │                 (if a product already exists, it's updated        │
 │                  instead of duplicated)                           │
 │        │                                                          │
 │        │  uses: db/session.py  → the connection to Postgres       │
 │        │        config.py      → the database address             │
 │        │        db/models.py   → what the products table looks    │
 │        │                         like                             │
 │        ▼                                                          │
 │   repeat ①–⑤ until the file is finished                           │
 └──────────────────────────────┬────────────────────────────────────┘
                                ▼
 ┌─ Postgres (in Docker) ────────────────────────────────────────────┐
 │ products table: one row per product, with search_text + embedding │
 │ Postgres fills in search_tsv (keyword data) by itself             │
 └───────────────────────────────────────────────────────────────────┘
```

Result: about 13 minutes for 30,000 products on a laptop CPU; almost all of it is step ④, embedding.
Because inserts are idempotent, re-running `load` updates rows in place instead of duplicating them.

## Each file's job in one line

| File (`src/catalog_copilot/`) | Job |
|---|---|
| `ingest/cli.py` | the command you type; decides whether to download or load |
| `ingest/pipeline.py` | runs the steps in order: the "manager" |
| `ingest/source.py` | reads records: from the internet (download) or from the local file (load) |
| `ingest/clean.py` | checks and cleans each record, and builds `search_text` |
| `embeddings.py` | turns `search_text` into 384 numbers with BGE (`embed_query` serves search later) |
| `db/models.py` | describes the `products` table (schema changes go through Alembic) |
| `db/session.py` + `config.py` | connect to Postgres (settings come from `CC_*` environment variables) |

## What a stored product looks like

`clean.py` turns a raw record into one labeled **product string**, `search_text`. This exact text is
what BGE embeds and what the reranker reads:

```
ASICS Women's GT-2000 9 Running Shoes. Brand: ASICS. Category: Women > Shoes > Athletic >
Running > Road Running. Gender: women. Features: Synthetic-and-mesh Imported Rubber sole ...
```

Price is deliberately **not** in `search_text`: numbers are enforced by SQL filters, not embeddings.
Features are cut at 500 characters (longer text embeds slower for little extra meaning).

| Column | Filled by | Used for |
|---|---|---|
| `search_text` | ingest | the reranker reads it; debugging what was embedded |
| `embedding` `vector(384)` | ingest (BGE-small, `passage_embed`) | vector search: matches meaning ("breathable" ≈ "mesh") |
| `search_tsv` `tsvector` | **Postgres** (generated column: title weight A, brand B, `search_text` C) | keyword search: exact words ("wide", "2E", brand names), GIN index |
| `price`, `brand`, `attributes` (JSONB: gender, color, material) | ingest | hard filters from the query parser |

There is no vector index at this size: an exact scan over 30K vectors takes ~12 ms. HNSW is planned
for the 1M scale run (measured: ~6 ms vs ~212 ms at 1M, but a 26-minute build and approximate
results). See [ADR 0006](adr/0006-exact-vector-scan-now-hnsw-at-scale.md) for the measurements.

### Embeddings
- Model: BGE-small (`BAAI/bge-small-en-v1.5`) via fastembed, running locally on the CPU (no API
  key). The model is downloaded once to `~/.cache/fastembed/` (configurable: `CC_MODEL_CACHE_DIR`).
- `embed_documents` takes a list of `search_text` strings and returns one 384-number vector per
  string, in the same order. Vectors are scaled to length 1, so dot product = cosine similarity.
- Products use `passage_embed`; queries will use `query_embed` (BGE adds a search instruction to
  queries). Both go through the same `Embedder`, so product and query vectors are comparable.
- Re-embedding the same text reproduces the stored vector (cosine 1.000000; batching changes the
  last decimal places only).

### Keyword data (`search_tsv`)
Our code never writes this column. Postgres computes it on every insert/update (a generated column
defined in migration 0001), reducing text to word roots with positions and weights:

```
"Breathable running shoes for wide feet, with a 2E width"
  -> 'breathabl':1 'run':2 'shoe':3 'wide':5 'feet':6 '2e':9 'width':10
```

Stop words ("for", "with") are dropped and words are stemmed ("running" -> `run`), so a query for
"run shoe" matches "running shoes". A GIN (inverted) index makes lookups fast. Keyword search catches
exact tokens that embeddings miss ("wide", "2E", brand names) but matches words, not products: a
search for "wide running shoes" also finds "Wide Shoelaces for Athletic Running Sneakers". That is
why search combines keyword and vector results and reranks them.

### Batching
`load` embeds and commits 256 products at a time (`--batch-size`). Each batch is committed before
the next, so a crash loses at most one batch and re-running is safe; memory stays flat from 30K to
1M products. The upper bound is ~6,500 rows per INSERT (Postgres allows 65,535 values per statement,
10 per row). Larger batches don't speed things up: embedding is the bottleneck.

## Data quality notes
- 47% of raw records have no price and are skipped; prices below $1 are placeholders and rejected.
- Coverage at 30K: brand 100% (from `store`), gender 98%, color 15% (listed or read from the
  title), material 4%. The dataset has no per-variant sizes, so there is no size filter.
