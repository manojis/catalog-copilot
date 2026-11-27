"""Candidate retrieval: keyword (Postgres full-text) and vector (pgvector) search.

Both take the same SQL filters from ``build_filters`` and return product ids, best first.
Only the rank order matters downstream: RRF merges the two lists by position.
"""

from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, cast, func, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from catalog_copilot.db.models import EMBEDDING_DIM, TEXT_SEARCH_CONFIG, Product

CANDIDATE_LIMIT = 50

_CONFIG = cast(TEXT_SEARCH_CONFIG, REGCONFIG)


def keyword_search(
    session: Session,
    text: str,
    filters: Sequence[ColumnElement[bool]] = (),
    limit: int = CANDIDATE_LIMIT,
) -> list[str]:
    """Full-text search on ``search_tsv``: products with ALL the words first, then ANY word.

    Requiring every word is precise for short queries ("rain jacket": 174 matches) but starves
    long ones ("breathable running shoes for wide feet": 4). So when the all-words query
    returns fewer than ``limit``, products matching any word fill the remaining slots, ranked
    below every all-words match.
    """
    if not text.strip():
        return []
    # websearch_to_tsquery: words are ANDed; also understands "quoted phrases" and "or".
    all_words = func.websearch_to_tsquery(_CONFIG, text)
    ids = list(session.scalars(_ranked(all_words, filters, limit)))
    if len(ids) < limit:
        any_word = func.to_tsquery(
            _CONFIG,
            func.array_to_string(func.tsvector_to_array(func.to_tsvector(_CONFIG, text)), " | "),
        )
        more = _ranked(any_word, [*filters, Product.id.not_in(ids)], limit - len(ids))
        ids.extend(session.scalars(more))
    return ids


def _ranked(
    query: ColumnElement[object], filters: Sequence[ColumnElement[bool]], limit: int
) -> Select[str]:
    # ts_rank_cd (cover density) rewards query words appearing close together, and uses the
    # title > brand > text weights. Plain ts_rank saturates near 1.0, so ties hide the order.
    rank = func.ts_rank_cd(Product.search_tsv, query)
    return (
        select(Product.id)
        .where(Product.search_tsv.op("@@")(query), *filters)
        .order_by(rank.desc(), Product.id)  # id breaks ties, so results are repeatable
        .limit(limit)
    )


def vector_search(
    session: Session,
    query_vector: Sequence[float],
    filters: Sequence[ColumnElement[bool]] = (),
    limit: int = CANDIDATE_LIMIT,
) -> list[str]:
    """The products whose stored embedding is closest to the query vector (cosine distance).

    ``query_vector`` comes from ``Embedder.embed_query`` (BGE), the same model that embedded the
    products at ingest; vectors from different models can't be compared. With no vector index
    (ADR 0006) this is an exact scan: every product that passes the filters is compared.
    """
    if len(query_vector) != EMBEDDING_DIM:
        raise ValueError(f"query vector has {len(query_vector)} numbers, expected {EMBEDDING_DIM}")
    distance = Product.embedding.cosine_distance(list(query_vector))  # SQL: embedding <=> :vector
    stmt = (
        select(Product.id)
        .where(*filters)
        .order_by(distance, Product.id)  # smallest distance first; id breaks ties
        .limit(limit)
    )
    return list(session.scalars(stmt))
