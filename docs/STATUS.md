# Status: catalog-copilot

_Last updated: 2026-10-17. Update this file at the end of every milestone._

## Current phase
Phase 3: Scaffold done. Next: Phase 4, milestone 1 of 6.

## Milestones
- [ ] M1 Catalog + hybrid search: **next**
- [ ] M2 RAG Q&A + web UI
- [ ] M3 CI/CD + live deploy (Fly.io)
- [ ] M4 Eval gate
- [ ] M5 Guardrails
- [ ] M6 Supplier extraction + taxonomy + final README

## How to run
`uv sync && uv run catalog-copilot` → http://127.0.0.1:8000/health

## Decisions made along the way
- 2026-10-17: Dataset = Amazon Reviews 2023 Clothing/Shoes/Jewelry (~30K subset); no free Nordstrom catalog exists.
- 2026-10-17: Provider-agnostic LLM layer (LiteLLM); Claude default, OpenAI optional.
- 2026-10-17: Hosting = Fly.io (user chose it over free Render + Neon).
- 2026-10-17: Repo created by user as **public**, Apache-2.0, and kept public. Strict secrets hygiene (.env + GitHub Secrets only).
- 2026-10-17: Python 3.12 via uv (system Python is 3.9).

## Pending / blocked
- User accounts needed by M2/M3: Anthropic API key (prepaid credits), Fly.io account, LangSmith (free). OpenAI key optional.
