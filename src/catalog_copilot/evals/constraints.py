"""End-to-end constraint check: do returned products satisfy the limits the shopper stated?

PRD target: on queries with stated limits, >= 95% of returned products satisfy every limit.
Expected limits come from the golden set, written from the shopper's intent, NOT from the
parser's output. If the parser reads "under $100" correctly, SQL enforces it and every product
passes; a violation means the parser missed or misread a limit ("jacket for him", "a hundred
dollars"). So this measures the query parser end to end on realistic phrasing, and its parse
accuracy is the baseline the M2 LLM parser must beat.

Limits: products are checked against their stored attributes. If ingest stored a wrong gender or
color, this check can't see it; that needs human relevance labels (M4).
"""

import argparse
import logging
import statistics
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from catalog_copilot.config import get_settings
from catalog_copilot.search.brands import brand_key
from catalog_copilot.search.query_parser import ParsedQuery
from catalog_copilot.search.service import SearchHit, SearchResponse
from catalog_copilot.vocabulary import GENDER_MATCHES, Color, Gender

TARGET_SATISFACTION = 0.95
DEFAULT_DATASET = Path("evals/datasets/search_constraints.json")
DEFAULT_REPORT = Path("evals/reports/search_constraints.json")

logger = logging.getLogger(__name__)


class Expectation(BaseModel):
    """The hard limits a human reads in the query (same meaning as ParsedQuery's filters)."""

    model_config = ConfigDict(extra="forbid")

    price_min: Decimal | None = None
    price_min_inclusive: bool = True
    price_max: Decimal | None = None
    price_max_inclusive: bool = True
    gender: Gender | None = None
    color: Color | None = None
    brands: tuple[str, ...] = ()

    @property
    def has_limits(self) -> bool:
        return self.as_query().has_filters

    def as_query(self) -> ParsedQuery:
        return ParsedQuery(**self.model_dump())


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    query: str
    expect: Expectation
    kind: Literal["constraint", "trap"] = "constraint"  # trap: must create no filter
    note: str | None = None


class Dataset(BaseModel):
    description: str
    cases: list[Case]


class Searcher(Protocol):
    def search(self, query: str, limit: int = ...) -> SearchResponse: ...


def violations(expect: Expectation, hit: SearchHit) -> list[str]:
    """Which expected limits this product breaks (empty = satisfies every limit)."""
    problems: list[str] = []
    wanted = expect.as_query()
    if wanted.price_min is not None or wanted.price_max is not None:
        if hit.price is None:
            problems.append("no price")
        elif not wanted.matches_price(hit.price):
            problems.append(f"price {hit.price}")
    if expect.brands:
        key = brand_key(hit.brand or "")
        if not any(key[: len(b)] == b for b in map(brand_key, expect.brands)):
            problems.append(f"brand {hit.brand!r}")
    if expect.gender and hit.attributes.get("gender") not in GENDER_MATCHES[expect.gender]:
        problems.append(f"gender {hit.attributes.get('gender')!r}")
    if expect.color and hit.attributes.get("color") != expect.color:
        problems.append(f"color {hit.attributes.get('color')!r}")
    return problems


def parse_differences(expect: Expectation, parsed: ParsedQuery) -> list[str]:
    """How the parser's filters differ from the expected limits (empty = parsed correctly)."""
    diffs: list[str] = []
    for side in ("min", "max"):
        want, got = getattr(expect, f"price_{side}"), getattr(parsed, f"price_{side}")
        want_inc = getattr(expect, f"price_{side}_inclusive")
        got_inc = getattr(parsed, f"price_{side}_inclusive")
        if want != got or (want is not None and want_inc != got_inc):
            diffs.append(
                f"price_{side}: expected {_bound(want, want_inc)}, got {_bound(got, got_inc)}"
            )
    for field in ("gender", "color"):
        if getattr(expect, field) != getattr(parsed, field):
            diffs.append(
                f"{field}: expected {getattr(expect, field)}, got {getattr(parsed, field)}"
            )
    wanted_keys = [brand_key(b) for b in expect.brands]
    got_keys = [brand_key(b) for b in parsed.brands]
    # Parsed brands include the family ("adidas" -> "adidas Originals"): each must extend an
    # expected brand, and each expected brand must be present.
    if not all(w in got_keys for w in wanted_keys) or not all(
        any(g[: len(w)] == w for w in wanted_keys) for g in got_keys
    ):
        diffs.append(f"brands: expected {list(expect.brands)}, got {list(parsed.brands)}")
    return diffs


def _bound(value: Decimal | None, inclusive: bool) -> str:
    return "none" if value is None else f"{value} ({'incl' if inclusive else 'excl'})"


class CaseResult(BaseModel):
    id: str
    query: str
    kind: str
    results: int
    satisfied: int
    parse_differences: list[str]
    false_filter: bool  # a trap that created a filter
    violations: list[str]  # "title: problem", for the products that break a limit
    total_ms: float


class Report(BaseModel):
    generated_at: str
    embedding_model: str
    reranker_model: str
    limit: int
    cases: int
    products_checked: int  # returned products in cases with stated limits
    products_satisfied: int
    constraint_satisfaction: float
    target: float
    parse_accuracy: float  # cases whose filters exactly match the expected limits
    false_filters: int
    zero_result_cases: list[str]
    latency_ms_p50: float
    latency_ms_p95: float
    case_results: list[CaseResult]

    @property
    def passed(self) -> bool:
        return self.constraint_satisfaction >= self.target and self.false_filters == 0


def evaluate(searcher: Searcher, dataset: Dataset, limit: int = 10) -> Report:
    results: list[CaseResult] = []
    for case in dataset.cases:
        response = searcher.search(case.query, limit)
        # A list, not a dict keyed by title: catalogs have duplicate titles (product variants).
        problems = [(hit.title, violations(case.expect, hit)) for hit in response.results]
        results.append(
            CaseResult(
                id=case.id,
                query=case.query,
                kind=case.kind,
                results=len(response.results),
                satisfied=sum(1 for _, p in problems if not p),
                parse_differences=parse_differences(case.expect, response.parsed),
                false_filter=case.kind == "trap" and response.parsed.has_filters,
                violations=[f"{title[:60]}: {', '.join(p)}" for title, p in problems if p],
                total_ms=response.timings_ms["total"],
            )
        )

    limited = [r for r, c in zip(results, dataset.cases, strict=True) if c.expect.has_limits]
    checked = sum(r.results for r in limited)
    satisfied = sum(r.satisfied for r in limited)
    latencies = sorted(r.total_ms for r in results)
    settings = get_settings()
    return Report(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        embedding_model=settings.embedding_model,
        reranker_model=settings.reranker_model,
        limit=limit,
        cases=len(results),
        products_checked=checked,
        products_satisfied=satisfied,
        constraint_satisfaction=round(satisfied / checked, 4) if checked else 1.0,
        target=TARGET_SATISFACTION,
        parse_accuracy=round(sum(not r.parse_differences for r in results) / len(results), 4),
        false_filters=sum(r.false_filter for r in results),
        zero_result_cases=[r.id for r in results if r.results == 0],
        latency_ms_p50=round(statistics.median(latencies), 1),
        latency_ms_p95=round(latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))], 1),
        case_results=results,
    )


def load_dataset(path: Path) -> Dataset:
    return Dataset.model_validate_json(path.read_text())


def format_report(report: Report) -> str:
    lines = [
        f"Constraint satisfaction: {report.constraint_satisfaction:.1%} "
        f"({report.products_satisfied}/{report.products_checked} products; "
        f"target {report.target:.0%}) -> {'PASS' if report.passed else 'FAIL'}",
        f"Parse accuracy: {report.parse_accuracy:.1%} of {report.cases} queries",
        f"False filters on traps: {report.false_filters}",
        f"Zero-result queries: {', '.join(report.zero_result_cases) or 'none'}",
        f"Latency: p50 {report.latency_ms_p50} ms, p95 {report.latency_ms_p95} ms",
    ]
    for r in report.case_results:
        if r.parse_differences or r.violations or r.false_filter:
            lines.append(f"\n  [{r.id}] {r.query!r}: {r.satisfied}/{r.results} satisfy")
            lines.extend(f"    parse: {d}" for d in r.parse_differences)
            lines.extend(f"    violates: {v}" for v in r.violations[:3])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)

    from catalog_copilot.search.service import create_search_service  # loads models

    report = evaluate(create_search_service(), load_dataset(args.dataset), args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n")
    print(format_report(report))
    print(f"\nFull report: {args.output}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
