# 0003: Postgres in Docker for dev; integration tests on throwaway containers

- **Status:** Accepted
- **Date:** 2026-11-21

## Context
Developers need Postgres with pgvector without installing it on their machines, and the dev setup
should resemble production (Fly.io also runs containers). Tests that touch the database should
use a real Postgres, not mocks, without risking a developer's local data.

## Decision
- `docker-compose.yml` runs `pgvector/pgvector:0.8.0-pg17` with a named volume (data survives
  restarts) and `shm_size: 2gb` (Docker's 64 MB default breaks parallel HNSW index builds).
  The app runs on the host in development; it is containerized in M3.
- Integration tests (`tests/integration/`, marker `integration`) start a fresh Postgres container
  per test session with testcontainers, run the migrations, and discard it afterwards.
- `tests/conftest.py` defaults `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`, the
  socket path inside the Docker VM, so tests work on Docker Desktop, Rancher Desktop and Linux
  without shell setup. If Docker isn't running the tests skip; any other Docker error fails.

## Consequences
- Any Docker runtime works (Docker Desktop, Rancher Desktop, Colima, Linux).
- Integration tests need Docker; `pytest -m "not integration"` runs the unit tests without it.
- Local credentials (`catalog`/`catalog`) are dev-only defaults; hosted environments use secrets.
