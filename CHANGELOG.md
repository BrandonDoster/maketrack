# Changelog

All notable changes to this project will be documented here. Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Project skeleton: FastAPI app, Pydantic-Settings config, structlog JSON logging, request-id middleware, `/healthz`.
- pyproject + uv lock, ruff config, pytest with httpx async client.
- Multi-stage Dockerfile (uv export -> pip slim image), non-root user, embedded Tailwind compile.
- CI workflow (ruff + pytest) and release workflow (multi-arch GHCR build on `v*.*.*` tags).
- DB foundation (M2): async SQLAlchemy 2 engine on aiosqlite, SQLite `PRAGMA foreign_keys=ON`, declarative `Base` with timestamp mixin.
- ORM models for all ten tables (external_sources, filaments, inventory_items, printers, models, model_assets, projects, project_models, project_filaments, project_items).
- Initial alembic migration covering all tables, indices, and FKs (incl. circular models ↔ model_assets via `use_alter`).
- Filament service with `assert_writable` enforcement raising `RemoteFilamentError` for non-local rows.
- Filament JSON CRUD routes (`/api/filaments`); 409 with structured body for read-only sources, 404 with `{error, entity, entity_id}` for missing rows.
- `/healthz` now pings the DB; returns 503 on connection failure.
- factory-boy factories and pytest fixtures wiring a fresh per-test SQLite + sessionmaker; alembic round-trip test verifies upgrade/downgrade.
