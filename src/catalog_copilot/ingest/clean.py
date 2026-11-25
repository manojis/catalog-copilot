"""Turn one raw Amazon record into a validated ProductRecord (pure functions, no I/O)."""

import html
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel

ROOT_CATEGORY = "Clothing, Shoes & Jewelry"
# Below $1 the dataset has placeholder prices ($0.01 rings, sunglasses ...), not real ones.
MIN_PRICE = Decimal("1.00")
MAX_PRICE = Decimal("10000")
MAX_FEATURES_CHARS = 500  # longer text = slower embedding, little extra signal
MAX_DESCRIPTION_CHARS = 2000

# details["Department"] values seen in the data -> our gender filter values
GENDER_BY_DEPARTMENT = {
    "womens": "women",
    "women": "women",
    "mens": "men",
    "men": "men",
    "unisex-adult": "unisex",
    "unisex adult": "unisex",
    "unisex": "unisex",
    "girls": "girls",
    "boys": "boys",
    "unisex-child": "kids",
    "baby-girls": "baby",
    "baby-boys": "baby",
    "unisex-baby": "baby",
}
# Fallback when Department is missing: categories[1] ("Women", "Men", ...)
GENDER_BY_CATEGORY = {
    "Women": "women",
    "Men": "men",
    "Girls": "girls",
    "Boys": "boys",
    "Baby": "baby",
}

COLORS = (
    "black", "white", "gray", "navy", "blue", "red", "green", "pink", "purple", "brown",
    "beige", "yellow", "orange", "gold", "silver", "khaki", "tan", "ivory", "burgundy",
    "olive", "teal", "maroon", "cream", "charcoal",
)  # fmt: skip
COLOR_ALIASES = {"grey": "gray"}
_COLOR_RE = re.compile(r"\b(" + "|".join((*COLORS, *COLOR_ALIASES)) + r")\b", re.IGNORECASE)

MATERIAL_KEYS = ("Material", "Material Type", "Fabric Type")


class SkipRecord(Exception):
    """Raised when a raw record can't become a product; the message is the reason."""


class ProductRecord(BaseModel):
    id: str
    title: str
    brand: str | None
    category_path: str | None
    price: Decimal
    attributes: dict[str, str]
    description: str | None
    url: str
    search_text: str


def normalize_text(value: Any) -> str:
    """Unescape HTML entities and collapse whitespace."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split())


def parse_price(value: Any) -> Decimal | None:
    """A price in [MIN_PRICE, MAX_PRICE), rounded to cents; None if missing or implausible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        price = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except InvalidOperation:
        return None
    price = price.quantize(Decimal("0.01"))
    if not (MIN_PRICE <= price < MAX_PRICE):
        return None
    return price


def normalize_gender(details: dict[str, Any], categories: list[str]) -> str | None:
    department = normalize_text(details.get("Department")).lower()
    if department in GENDER_BY_DEPARTMENT:
        return GENDER_BY_DEPARTMENT[department]
    if len(categories) > 1:
        return GENDER_BY_CATEGORY.get(categories[1])
    return None


def extract_color(details: dict[str, Any], title: str) -> str | None:
    """The listed color if it names a known color, else the first known color word in the title."""
    for text in (normalize_text(details.get("Color")), title):
        if match := _COLOR_RE.search(text):
            word = match.group(1).lower()
            return COLOR_ALIASES.get(word, word)
    return None


def extract_material(details: dict[str, Any]) -> str | None:
    for key in MATERIAL_KEYS:
        if material := normalize_text(details.get(key)):
            return material.lower()
    return None


def build_category_path(categories: list[str]) -> str | None:
    parts = [normalize_text(c) for c in categories if normalize_text(c) != ROOT_CATEGORY]
    return " > ".join(p for p in parts if p) or None


def truncate(text: str, limit: int) -> str:
    """Cut at a word boundary so we never embed half a word."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0]


def build_search_text(
    title: str,
    brand: str | None,
    category_path: str | None,
    attributes: dict[str, str],
    features: list[str],
) -> str:
    """The one product string that BGE embeds and the reranker reads.

    Labeled fields help both models: e.g. "Category: ... Running Shoes" tells the reranker
    what a product is even when the title is only a model name.
    """
    parts = [title]
    if brand:
        parts.append(f"Brand: {brand}")
    if category_path:
        parts.append(f"Category: {category_path}")
    parts.extend(f"{key.capitalize()}: {value}" for key, value in attributes.items())
    feature_text = truncate(" ".join(normalize_text(f) for f in features), MAX_FEATURES_CHARS)
    if feature_text:
        parts.append(f"Features: {feature_text}")
    return ". ".join(parts)


def clean_record(raw: dict[str, Any]) -> ProductRecord:
    """Validate and normalize one raw record. Raises SkipRecord if it can't be used."""
    asin = normalize_text(raw.get("parent_asin"))
    if not asin:
        raise SkipRecord("missing id")
    title = normalize_text(raw.get("title"))
    if not title:
        raise SkipRecord("missing title")
    price = parse_price(raw.get("price"))
    if price is None:
        raise SkipRecord("missing or invalid price")

    details: dict[str, Any] = raw.get("details") or {}
    categories: list[str] = raw.get("categories") or []
    brand = normalize_text(raw.get("store")) or normalize_text(details.get("Brand")) or None
    category_path = build_category_path(categories)

    attributes: dict[str, str] = {}
    if gender := normalize_gender(details, categories):
        attributes["gender"] = gender
    if color := extract_color(details, title):
        attributes["color"] = color
    if material := extract_material(details):
        attributes["material"] = material

    description = truncate(
        normalize_text(" ".join(raw.get("description") or [])), MAX_DESCRIPTION_CHARS
    )

    return ProductRecord(
        id=asin,
        title=title,
        brand=brand,
        category_path=category_path,
        price=price,
        attributes=attributes,
        description=description or None,
        url=f"https://www.amazon.com/dp/{asin}",
        search_text=build_search_text(
            title, brand, category_path, attributes, raw.get("features") or []
        ),
    )
