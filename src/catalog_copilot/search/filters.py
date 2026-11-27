"""Turn a ParsedQuery's hard filters into SQL conditions on the products table.

The same conditions go into both the keyword and the vector search, so each search only ranks
products that qualify. Values are bound parameters, never pasted into the SQL string.
"""

from sqlalchemy import ColumnElement, func, or_

from catalog_copilot.db.models import Product
from catalog_copilot.search.query_parser import ParsedQuery
from catalog_copilot.vocabulary import GENDER_MATCHES


def build_filters(parsed: ParsedQuery) -> list[ColumnElement[bool]]:
    """SQL conditions for every filter in the query (an empty list means no filtering)."""
    conditions: list[ColumnElement[bool]] = []

    if parsed.price_min is not None:
        conditions.append(
            Product.price >= parsed.price_min
            if parsed.price_min_inclusive
            else Product.price > parsed.price_min
        )
    if parsed.price_max is not None:
        conditions.append(
            Product.price <= parsed.price_max
            if parsed.price_max_inclusive
            else Product.price < parsed.price_max
        )

    if parsed.brands:  # matches the lower(brand) index
        conditions.append(func.lower(Product.brand).in_([b.lower() for b in parsed.brands]))

    # attributes @> '{"gender": "women"}' can use the GIN index on attributes; ->> can't.
    if parsed.gender:
        conditions.append(
            or_(
                *(Product.attributes.contains({"gender": g}) for g in GENDER_MATCHES[parsed.gender])
            )
        )
    if parsed.color:
        conditions.append(Product.attributes.contains({"color": parsed.color}))

    return conditions
