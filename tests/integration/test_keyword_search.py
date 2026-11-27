"""Keyword search against a real Postgres (stemming, ranking and search_tsv all live there)."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from catalog_copilot.db.models import Product
from catalog_copilot.search.filters import build_filters
from catalog_copilot.search.query_parser import ParsedQuery
from catalog_copilot.search.retrieval import keyword_search
from tests.integration.factories import make_product

pytestmark = pytest.mark.integration

PRODUCTS = [
    make_product("COAT1", "Warm winter coat with hood", price="120.00"),
    make_product("COAT2", "Winter coat, lightweight", price="60.00"),
    make_product("SOCK", "Warm wool socks", price="15.00"),
    make_product("RAIN", "Rain jacket", price="40.00"),
    make_product("BOOT_TITLE", "Hiking boots", price="90.00"),
    make_product("BOOT_TEXT", "Trail hiker", price="90.00", search_text="Trail hiker. Boots."),
    make_product("SHOE", "Shoe for running", price="70.00"),
]


@pytest.fixture(scope="module")
def session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as session:
        session.execute(delete(Product))
        session.add_all(PRODUCTS)
        session.commit()
        yield session
        session.execute(delete(Product))
        session.commit()


def test_all_words_matches_rank_above_any_word_matches(session: Session) -> None:
    ids = keyword_search(session, "warm winter coat")
    assert ids[0] == "COAT1"  # the only product with all three words
    assert set(ids[1:]) == {"COAT2", "SOCK"}  # some of the words, ranked after
    assert "RAIN" not in ids  # none of the words


def test_no_relaxation_when_all_words_fill_the_limit(session: Session) -> None:
    assert keyword_search(session, "warm winter coat", limit=1) == ["COAT1"]


def test_filters_apply_to_both_passes(session: Session) -> None:
    under_100 = build_filters(ParsedQuery(price_max=Decimal("100"), price_max_inclusive=False))
    # COAT1 ($120) is filtered out, so no product has all words; the any-word pass fills in.
    assert set(keyword_search(session, "warm winter coat", under_100)) == {"COAT2", "SOCK"}


def test_words_are_stemmed(session: Session) -> None:
    assert keyword_search(session, "running shoes") == ["SHOE"]  # running->run, shoes->shoe


def test_title_match_ranks_above_text_only_match(session: Session) -> None:
    assert keyword_search(session, "boots") == ["BOOT_TITLE", "BOOT_TEXT"]


@pytest.mark.parametrize("text", ["", "   ", "for the"])  # empty, blank, only stop words
def test_nothing_to_search_returns_nothing(session: Session, text: str) -> None:
    assert keyword_search(session, text) == []


def test_results_are_repeatable(session: Session) -> None:
    assert keyword_search(session, "warm winter coat") == keyword_search(
        session, "warm winter coat"
    )
