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
- Filaments + sources (M3): UI shell with Tailwind (CDN+static fallback), vendored htmx/alpine, dashboard, filament list/new/edit/archive pages, sources list/new/edit pages, "Sync now" button.
- External sources CRUD (JSON + UI), per-source TTL, atomic per-source sync lock.
- Source adapter contract (`FilamentSource` Protocol + `ExternalFilament` dataclass); `SpoolmanFilamentSource` mapping `id/filament.{name,material,color_hex,vendor.name,diameter,weight}/remaining_weight` against the live Spoolman v0.23 API.
- Sync engine: per-source lock acquire, full pull, upsert by `(source, external_id)`, archive sweep on success, reappearance clears `archived_at`, lock released cleanly on failure.
- Lazy sync on filament browse (TTL-driven), manual `POST /api/sources/{id}/sync`, daily APScheduler tick over enabled sources via FastAPI lifespan.
- `RemoteFilamentError` → 409 + structured body for JSON callers; HTML "Open in [source]" banner partial for UI callers.
- Disabling a source archives all its filaments; re-enable + sync un-archives any that come back.
- Tests: spoolman adapter (mocked transport), sync engine semantics (upsert, archive sweep, reappearance, lock skip, fail-leaves-rows), sources CRUD routes, UI smoke. 43 tests total.
