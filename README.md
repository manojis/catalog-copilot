# catalog-copilot

LLM-powered product catalog assistant for PIM: RAG search with citations, supplier attribute
extraction, and taxonomy classification. Provider-agnostic, with RAGAS/LangSmith evals and
guardrails enforced in CI/CD.

> Status: early development. See [docs/STATUS.md](docs/STATUS.md).

## Quick start

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                    # install Python 3.12 + dependencies
cp .env.example .env
uv run catalog-copilot     # http://127.0.0.1:8000/health  (API docs at /docs)
```

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

## Docs
- [Product requirements](docs/PRD.md)
- [Technical design](docs/DESIGN.md)
- [Status](docs/STATUS.md)

## Data
Product data from [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/) (McAuley Lab),
used for non-commercial research/demo purposes.

## License
Apache-2.0
