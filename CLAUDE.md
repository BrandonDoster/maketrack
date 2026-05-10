# MakeTrack

A self-hosted 3D printing project tracker with inventory, filament management, and pluggable external filament sources. Single-user, LAN-only, AGPL-3.0. Ships as a single Docker container on GHCR.

This file is the project spec. Read it before making non-trivial decisions about scope, schema, or architecture, and update it when those decisions change.

## What it does

- Tracks 3D printing **projects** with status, attached models, BOM (filament + hardware), and printer assignment.
- Tracks **models** as reusable entities (a model = one printable thing with multiple file assets like STL, STEP, 3MF, plus a thumbnail). Models are standalone; projects link to them.
- Tracks **filament** locally OR sourced from external systems (Spoolman first). Local filament is the fallback. External sources are preferred where available.
- Tracks **inventory** (hardware, electronics, parts) with quantity tracking and BOM-driven "what do I still need to buy" rollups.
- Tracks **printers** as first-class entities with a generic access URL (not Klipper-specific). Projects link to which printer printed them.
- Exposes a read-only **MCP server** for queries like "status of my projects" or "do I have enough filament for X". Write tools land later.

## What it doesn't do (v1, explicitly out of scope)

So Claude Code doesn't try to build these:

- Moonraker / Klipper integration for live print job tracking
- In-app backup/restore (volume snapshots are the answer for v1)
- Multi-user auth (single user, no auth, LAN-only)
- Print queue / scheduling
- NFC / OpenPrintTag (handled by Spoolman or other future filament sources, not by local filament)
- 3MF or STEP 3D preview (download only; STL preview is in v1)
- Auto-thumbnail generation from STL geometry (manual upload + 3MF embedded extraction in v1)
- Printables / Thingiverse metadata enrichment (schema is designed for it; implementation is later)
- GitHub repo or direct-URL import for model files
- Maintenance schedules / part-life tracking
- Bulk upload with auto-grouping suggestions

Local filament management is intentionally a fallback. Spoolman or other external sources are the preferred path. Don't over-invest in local-only filament features.

## Planned (post-v1, schema lives here so we don't paint into a corner)

These are deferred but the data model should accommodate them so we don't end up doing destructive migrations later.

- **Printer photo + mod list with project link.** A printer has zero or more mods. A mod has a name, optional notes, an optional photo, and an optional FK to a `projects.id` (the project that built/added the mod — useful when you printed your own riser feet). Schema sketch: `printer_mods (id, printer_id NOT NULL FK, name NOT NULL, description, photo_path, source_project_id FK projects, created_at, updated_at)`. Add `printers.photo_path TEXT NULL` for a primary printer photo.
- **Inventory ↔ printer parts tracking.** A printer is partly an assembly of inventory items (heatset inserts, bolts, board, hotend, etc.). Track which items are currently installed in which printer so a teardown can reclaim them. Schema sketch: `printer_parts (id, printer_id FK CASCADE, inventory_item_id FK RESTRICT, qty NOT NULL DEFAULT 1, installed_at, removed_at NULL, notes)`. "Reclaim" UI bumps `removed_at`, increments `inventory_items.quantity` by `qty`.
- **Locations for inventory.** Promote the `inventory_items.location` text field to a structured `locations` table (`id, name, kind ('bin'|'shelf'|'drawer'|'other'), parent_id NULL, qr_code NULL`) with `inventory_items.location_id FK NULL`. Settings page lists/edits locations.
- **QR codes for items and bins.** When the location/item rows have stable URLs, render a QR code that decodes to the item or location detail page. Mobile flow: scan a bin QR, see what's in it; scan an item then a bin to move it; scan a bin while putting away an order to add new items there.
- **Slicer-aware filament estimator.** Today `project_filaments.est_weight_g` is hand-entered. Goal: (a) per-project preset (`standard`, `voron`, `prusa_strong`, etc.) that applies an `infill × walls` multiplier to the model's bounding-box volume + filament density to ballpark grams; (b) parse the slice metadata embedded in a 3MF (Bambu/Orca write `Metadata/slice_info.config` with `filament_used` per spool) and use that as the source of truth when present; (c) per-`project_filament` row override so the user can correct after weighing the spool. Schema sketch: `slicer_presets (id, name, infill_multiplier, wall_multiplier, density_g_cm3)`; new column `project_filaments.estimate_source TEXT` (`manual` | `preset:<name>` | `3mf` | `override`).
- **Pagination on the list pages.** M8 added search + filters but skipped pagination — at realistic homelab scales (<200 rows per list) it's noise. Add it when the filaments table crosses a few hundred spools or the models grid is clearly slow. Likely shape: `?page=N` query param with a fixed page size (50?), `prev` / `next` chips alongside the existing search toolbar, server-side `LIMIT/OFFSET`. Skip on projects + printers (low cardinality).

## Licensing and prior art

- License: **AGPL-3.0**.
- Inspired by [Print Vault](https://github.com/shaxs/print-vault) (AGPL-3.0, Django/Vue/Postgres). Inspiration only, no code, schema, or migrations copied.
- Hooks into [Spoolman](https://github.com/Donkie/Spoolman) (MIT, FastAPI) via its documented REST API. No code copied.

## Tech stack

- Python 3.12+
- FastAPI + SQLAlchemy 2.0 async + Alembic + aiosqlite
- HTMX + Alpine.js + Tailwind CSS (Tailwind compiled at build time, no Node runtime in the final image)
- three.js + STLLoader, lazy-loaded only on the model detail page
- Pydantic-Settings for env-driven config
- structlog for JSON logging
- pytest + httpx test client + factory-boy
- ruff for lint and format
- uv for local dev dependency resolution; production image uses pip from an exported requirements.txt

### Why these choices

- Server-rendered HTMX over an SPA: this is internal tooling (forms, tables, detail pages). No build pipeline complexity, no two-deploy story, no CORS. Tailwind gives a polished look without design effort.
- SQLite over Postgres: single-user homelab tool. SQLite is plenty, makes the container simpler, and backups become "copy a file."
- FastAPI: async-friendly for Spoolman sync, Pydantic models match how external API mapping works, and matches Spoolman's own stack which makes the integration mental model clean.
- AGPL: anyone running a hosted version must share their changes.

## Repo layout

```
maketrack/
├── .github/workflows/
│   ├── ci.yml                  # ruff + pytest on PR and push to main
│   └── release.yml             # build & push to GHCR on tag (v*.*.*)
├── src/maketrack/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entrypoint
│   ├── config.py               # Pydantic-Settings
│   ├── db.py                   # SQLAlchemy engine, session
│   ├── models/                 # SQLAlchemy ORM, one file per domain
│   ├── schemas/                # Pydantic API schemas
│   ├── routes/                 # FastAPI routers, one per domain
│   ├── services/               # business logic, source-of-truth for read-only enforcement and BOM rollups
│   ├── sources/                # external source adapters
│   │   ├── base.py             # FilamentSource protocol
│   │   ├── local.py
│   │   └── spoolman.py
│   ├── sync/                   # sync engine, TTL, locking
│   ├── mcp/                    # MCP server entrypoint and tools
│   ├── templates/              # Jinja2 templates for HTMX responses
│   ├── static/                 # compiled Tailwind CSS, three.js bundle, alpine
│   └── alembic/                # migrations
├── tests/
├── pyproject.toml              # uv-managed
├── uv.lock
├── Dockerfile                  # multi-stage: build (uv) + final (slim + pip)
├── docker-compose.example.yml
├── README.md
├── CLAUDE.md                   # this file
└── LICENSE                     # AGPL-3.0
```

## Container build

Multi-stage Dockerfile:

1. **Build stage** (`python:3.12 AS build`):
   - Install uv
   - Copy `pyproject.toml` + `uv.lock`
   - Export `requirements.txt` with `uv export --no-dev --format requirements-txt -o requirements.txt`
   - Compile Tailwind into `src/maketrack/static/tailwind.css`
2. **Final stage** (`python:3.12-slim`):
   - Copy `requirements.txt` from build stage
   - `pip install --no-cache-dir -r requirements.txt`
   - Copy app source + compiled static assets
   - Create non-root `maketrack` user, drop privileges
   - `EXPOSE 8000`
   - Healthcheck calls `/healthz`
   - CMD runs uvicorn

No uv binary in the final image.

Volumes (mount in compose):

- `/data` — SQLite DB at `/data/maketrack.db`
- `/uploads` — model assets and photos

GHCR publish on `v*.*.*` tags. Tags pushed: `vX.Y.Z` always, `latest` only on non-prerelease tags. Build multi-arch (`linux/amd64`, `linux/arm64`).

## Configuration

All via env vars, prefix `MAKETRACK_`, parsed by Pydantic-Settings.

| Var | Default | Purpose |
|---|---|---|
| `MAKETRACK_DB_PATH` | `/data/maketrack.db` | SQLite path |
| `MAKETRACK_UPLOADS_PATH` | `/uploads` | Asset storage root |
| `MAKETRACK_LOG_LEVEL` | `INFO` | structlog level |
| `MAKETRACK_BIND_HOST` | `0.0.0.0` | uvicorn bind address |
| `MAKETRACK_BIND_PORT` | `8000` | uvicorn port |
| `MAKETRACK_DEFAULT_TTL_SECONDS` | `86400` | Default per-source sync TTL |

External source connections (Spoolman base URL, auth tokens, field map) live in the `external_sources` table, not env vars. They're configured through the UI.

## Data model

All tables include `created_at` and `updated_at` timestamps. SQLite via aiosqlite.

### filaments

```sql
filaments (
  id                  INTEGER PRIMARY KEY,
  source              TEXT NOT NULL,            -- 'local' | 'spoolman' | future
  source_id           INTEGER,                  -- FK to external_sources.id; NULL for 'local'
  external_id         TEXT,                     -- ID in source system; NULL for 'local'
  external_url        TEXT,                     -- deep link to manage in source

  name                TEXT,
  material            TEXT,
  color_hex           TEXT,
  brand               TEXT,
  diameter_mm         REAL,
  total_weight_g      REAL,
  remaining_weight_g  REAL,
  notes               TEXT,

  last_synced_at      TIMESTAMP,
  archived_at         TIMESTAMP,                -- soft delete
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP,

  UNIQUE (source, external_id)
)
```

`source = 'local'` rows are editable. All others are read-only at the service layer; edit attempts raise `RemoteFilamentError(source, external_url)` and the UI renders the error as a banner with an "Open in [source]" button using `external_url`.

### external_sources

```sql
external_sources (
  id                  INTEGER PRIMARY KEY,
  type                TEXT NOT NULL,            -- 'spoolman'
  name                TEXT NOT NULL,            -- user label, e.g. "home spoolman"
  base_url            TEXT,
  auth_token          TEXT,                     -- nullable
  field_map           JSON,                     -- maps source response shape to filaments columns
  ttl_seconds         INTEGER DEFAULT 86400,
  last_synced_at      TIMESTAMP,
  sync_in_progress    BOOLEAN DEFAULT FALSE,
  enabled             BOOLEAN DEFAULT TRUE,
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP
)
```

### inventory_items

Hardware, electronics, anything that isn't filament.

```sql
inventory_items (
  id                  INTEGER PRIMARY KEY,
  name                TEXT NOT NULL,
  category            TEXT,                     -- 'hardware' | 'electronic' | 'tool' | 'other'
  description         TEXT,
  quantity            INTEGER NOT NULL DEFAULT 0,
  reorder_threshold   INTEGER,
  unit                TEXT,                     -- 'each' | 'm' | 'mm' | 'kg' | etc
  vendor              TEXT,
  vendor_sku          TEXT,
  vendor_url          TEXT,
  notes               TEXT,
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP
)
```

### printers

```sql
printers (
  id                  INTEGER PRIMARY KEY,
  name                TEXT NOT NULL,
  model               TEXT,                     -- 'Voron 2.4', 'Bambu X1C', etc
  access_url          TEXT,                     -- generic URL to the printer's UI (Mainsail, OctoPrint, Bambu Studio, whatever)
  notes               TEXT,
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP
)
```

The "list of projects this printer is involved in" is a query against `projects.printer_id`, not a stored relationship.

### models

A printable thing. Standalone or linked to projects via `project_models`.

```sql
models (
  id                    INTEGER PRIMARY KEY,
  name                  TEXT NOT NULL,
  description           TEXT,
  source_type           TEXT,                   -- 'local' | 'printables' | 'thingiverse' | 'github' | 'other'
  source_url            TEXT,
  thumbnail_asset_id    INTEGER,                -- FK to model_assets.id; nullable
  notes                 TEXT,
  tags                  TEXT,                   -- JSON array of strings (v1); promote to a tags table later if it gets messy
  created_at            TIMESTAMP,
  updated_at            TIMESTAMP,

  FOREIGN KEY (thumbnail_asset_id) REFERENCES model_assets(id) ON DELETE SET NULL
)
```

### model_assets

Files attached to a model. Grouping is by `model_id`, not filename — the user (or upload flow) explicitly groups files into a model.

```sql
model_assets (
  id                  INTEGER PRIMARY KEY,
  model_id            INTEGER NOT NULL,
  asset_type          TEXT NOT NULL,            -- 'stl' | 'step' | '3mf' | 'gcode' | 'image' | 'other'
  filename            TEXT NOT NULL,            -- original filename, preserved for downloads
  file_path           TEXT NOT NULL,            -- relative to /uploads, e.g. 'models/<uuid>'
  file_size           INTEGER,
  sha256              TEXT,
  generated           BOOLEAN DEFAULT FALSE,    -- TRUE for 3MF-extracted thumbnails, etc.
  uploaded_at         TIMESTAMP,

  FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
)
```

Uploads stored flat as `/uploads/models/<uuid>` with the original filename only in `filename`. No path traversal possible because the user never picks a path. Original filename is preserved for downloads via `Content-Disposition`.

On 3MF asset upload: open as zip, extract embedded thumbnail PNG (OrcaSlicer commonly stores it at `Metadata/_rels/thumbnail.png` or `Metadata/plate_1.png` — check what's actually in the archive and fall back gracefully), save as a `model_asset` with `asset_type='image'` and `generated=true`. If the model has no `thumbnail_asset_id` set, point it at this new asset.

### projects

```sql
projects (
  id                  INTEGER PRIMARY KEY,
  name                TEXT NOT NULL,
  description         TEXT,
  status              TEXT NOT NULL DEFAULT 'planning',  -- 'planning' | 'printing' | 'done' | 'archived' | 'abandoned'
  printer_id          INTEGER,                  -- nullable FK to printers
  notes               TEXT,
  tags                TEXT,                     -- JSON array
  created_at          TIMESTAMP,
  updated_at          TIMESTAMP,
  completed_at        TIMESTAMP,

  FOREIGN KEY (printer_id) REFERENCES printers(id) ON DELETE SET NULL
)
```

### project_models

```sql
project_models (
  project_id          INTEGER NOT NULL,
  model_id            INTEGER NOT NULL,
  qty_to_print        INTEGER NOT NULL DEFAULT 1,
  status              TEXT DEFAULT 'pending',   -- 'pending' | 'printed' | 'failed'
  notes               TEXT,

  PRIMARY KEY (project_id, model_id),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE RESTRICT
)
```

### project_filaments

```sql
project_filaments (
  id                  INTEGER PRIMARY KEY,
  project_id          INTEGER NOT NULL,
  filament_id         INTEGER NOT NULL,
  est_weight_g        REAL,
  actual_weight_g     REAL,
  role                TEXT,                     -- 'extruder_0', 'extruder_1', 'supports', etc

  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (filament_id) REFERENCES filaments(id) ON DELETE RESTRICT
)
```

### project_items (BOM)

```sql
project_items (
  id                  INTEGER PRIMARY KEY,
  project_id          INTEGER NOT NULL,
  inventory_item_id   INTEGER NOT NULL,
  qty_required        INTEGER NOT NULL,
  qty_consumed        INTEGER NOT NULL DEFAULT 0,
  notes               TEXT,

  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (inventory_item_id) REFERENCES inventory_items(id) ON DELETE RESTRICT
)
```

The BOM rollup answers "for project X, how much do I still need to buy":

```sql
SELECT
  ii.name,
  pi.qty_required - pi.qty_consumed AS still_needed_for_project,
  ii.quantity AS on_hand,
  MAX(0, (pi.qty_required - pi.qty_consumed) - ii.quantity) AS still_to_buy
FROM project_items pi
JOIN inventory_items ii ON ii.id = pi.inventory_item_id
WHERE pi.project_id = ?
```

A dashboard "shopping list" aggregates `still_to_buy` across all projects with `status IN ('planning', 'printing')`, summing per `inventory_item_id` so the same bolt across two projects shows as one line.

## External source sync

### Adapter contract

```python
class FilamentSource(Protocol):
    async def list_spools(self) -> list[ExternalFilament]: ...
    async def health_check(self) -> bool: ...
```

Implementations:

- `LocalFilamentSource` — degenerate, reads/writes the local rows.
- `SpoolmanFilamentSource` — calls Spoolman REST API (`/api/v1/spool`), applies `field_map` from `external_sources.field_map` to transform Spoolman's response into the unified shape.

### Sync triggers

Per-source sync fires on:

1. **Lazy on browse** — on any request that reads filaments, check `now() - last_synced_at > ttl_seconds`. If stale, kick off a sync before serving the response. If no one's browsing, no sync runs.
2. **Manual** — "Sync now" button per source in the UI.
3. **Daily timer** — APScheduler job, fires once a day per enabled source regardless of `last_synced_at`.

### Sync semantics

1. Acquire per-source lock atomically: `UPDATE external_sources SET sync_in_progress = TRUE WHERE id = ? AND sync_in_progress = FALSE` — if zero rows updated, another sync is running, return.
2. Full pull from the source (paginated). Don't bother with `?updated_since=` until measurements show it matters.
3. Upsert each returned spool by `(source, external_id)`.
4. After successful pagination, run the archive sweep in a single transaction: any row with `source = X AND external_id NOT IN (returned_ids) AND archived_at IS NULL` → set `archived_at = NOW()`.
5. If pagination errors mid-way, leave existing rows alone (no archive sweep), log the failure, release the lock.
6. Update `last_synced_at = NOW()`, set `sync_in_progress = FALSE`.

If a previously-archived spool reappears in a sync result, clear its `archived_at`.

### Disabling a source

When a user sets `enabled = FALSE`:

- Stop scheduled and lazy syncs for it.
- Mark all of its rows as archived.
- Projects referencing those filaments still render. The UI shows them as "from disabled source: [name]".
- If the user re-enables, the next successful sync clears `archived_at` on rows that come back.

## Read-only enforcement

Single check at the service layer, applied everywhere a write would land:

```python
def assert_writable(filament: Filament) -> None:
    if filament.source != "local":
        raise RemoteFilamentError(
            source=filament.source,
            external_url=filament.external_url,
        )
```

Routes catch `RemoteFilamentError`:

- API/MCP callers get a 4xx with a structured body.
- HTMX UI callers get a rendered banner partial with the source name and an "Open in [source]" button linking to `external_url`.

## File handling

### Layout

```
/uploads/
  models/
    <uuid>          # one file per upload, original filename only in DB
```

Flat structure with UUID filenames. The user never sees or chooses the path. Original filename lives in `model_assets.filename` and is used on download via `Content-Disposition: attachment; filename="<original_filename>"` with content type inferred from `asset_type`.

### Upload endpoint

`POST /models/{model_id}/assets` accepts multipart, single or multiple files. For each:

1. Save to `/uploads/models/<uuid>`.
2. Compute SHA-256.
3. Insert `model_assets` row.
4. If `asset_type = '3mf'`: open the zip, look for an embedded thumbnail PNG, save it as a separate asset with `generated=true`. If the model has no thumbnail set, point `models.thumbnail_asset_id` at the new image asset.

### Thumbnails

- `models.thumbnail_asset_id` is a nullable FK to `model_assets.id`.
- The pointed asset is in the same model and has `asset_type = 'image'`.
- Set explicitly via the UI (Set as thumbnail button) or via the MCP `set_model_thumbnail` tool.
- Set automatically the first time a 3MF is uploaded if no thumbnail is yet set.
- Replace by changing the FK; the old image asset stays as a regular asset.

## 3D preview

STL only in v1. The model detail page lazy-loads three.js + STLLoader (~300 KB JS, only on that page) and renders the STL client-side. No server-side mesh processing.

3MF and STEP are download-only in v1. Format badges in the list view tell the user what's available. Phase 2 considers 3MF preview via three.js's `3MFLoader`. STEP preview is permanently out of scope — too heavy.

## MCP server

A separate FastAPI app within the same package, bound to localhost only. Talks to the same SQLite DB as the web app.

### v1 tools (read)

- `list_projects(status: str | None = None)` → list of projects
- `get_project(project_id: int)` → full detail with linked filaments, items, models, printer
- `list_models(tag: str | None = None, source_type: str | None = None)` → list of models
- `get_model(model_id: int)` → model with all assets
- `list_filaments(material: str | None = None, source: str | None = None)` → list of filaments
- `find_filament_for_project(project_id: int)` → for each `project_filaments` row, whether available remaining weight covers `est_weight_g`, and which spool to use
- `project_shopping_list(project_id: int | None = None)` → BOM-derived shopping list, defaulting to all active projects
- `list_printers()` → list of printers

### v1 tools (write, scoped to model creation)

- `create_model(name, description, source_type, source_url)` → new model
- `upload_model_asset(model_id, asset_type, content, set_as_thumbnail=False)` → new asset; `content` accepts MCP image content blocks for image uploads, base64 for binary file types
- `set_model_thumbnail(model_id, asset_id)` → updates `models.thumbnail_asset_id`

Other writes (project create/update, filament edit, inventory edit) come in phase 2. v1 keeps writes scoped to model creation because that's the highest-friction path through the UI.

### MCP auth

None. The server binds to localhost only. The caller is assumed to be the same single user who runs the web app.

## Auth (web app)

None for v1. The container binds to `0.0.0.0:8000` and the user runs it on their LAN behind their firewall.

A FastAPI dependency `current_user()` returns a hardcoded singleton user. Routes use it everywhere. When auth is added in phase 2, only that dependency changes.

## Logging

structlog, JSON to stdout. Standard fields: `timestamp`, `level`, `event`, `request_id` (per-request UUID via middleware), `user_id` (hardcoded for v1).

Sync runs log a structured event with `source_id`, `started_at`, `finished_at`, `rows_upserted`, `rows_archived`, `error`.

## Healthcheck

`GET /healthz` returns `200` with `{"status": "ok", "version": "X.Y.Z"}` if the SQLite connection works. Used by the Docker healthcheck.

## CI / Release

### CI (`.github/workflows/ci.yml`)

On every PR and push to `main`:

1. `uv sync --dev`
2. `uv run ruff check`
3. `uv run ruff format --check`
4. `uv run pytest`

### Release (`.github/workflows/release.yml`)

On push of a tag matching `v*.*.*`:

1. Build multi-arch (`linux/amd64`, `linux/arm64`) Docker image.
2. Tag as `ghcr.io/<owner>/maketrack:vX.Y.Z`. Tag as `:latest` only on non-prerelease tags.
3. Push to GHCR.

## Conventions

- **Migrations**: alembic. Generate with `alembic revision --autogenerate`, but always review the generated file before commit. Hand-edit anything autogenerate gets wrong.
- **Async everywhere** in the request path. No sync DB calls in async routes or services.
- **Pydantic schemas separate from ORM models.** API request/response bodies live in `schemas/`. Don't return ORM objects from routes.
- **No raw SQL outside alembic migrations.** Use SQLAlchemy 2.0-style `select()` everywhere else.
- **Service layer owns business rules.** Routes are thin: parse input, call service, render response. Read-only enforcement, sync logic, BOM rollups all live in services.
- **Tests**: every route has a happy-path test. Service layer has unit tests for business rules. Sync engine has tests with a mocked Spoolman.
- **Commits**: conventional commits style (`feat:`, `fix:`, `chore:`, `docs:`). Squash on merge. The release workflow is tag-driven, not commit-message-driven.

## First-pass implementation order

The order minimizes blocking dependencies and gets a useful tool standing by milestone 4.

1. **Skeleton** — pyproject, ruff config, Dockerfile, `main.py` with `/healthz`, structured logging, Pydantic-Settings. CI green on an empty pytest run.
2. **DB foundation** — alembic init, all tables from this doc, factory-boy fixtures, basic CRUD service for filaments end-to-end.
3. **Filaments + sources** — local filament CRUD via UI, `external_sources` CRUD via UI, Spoolman adapter, sync engine (lazy + manual + daily), read-only enforcement with the "Open in source" banner pattern.
4. **Inventory + printers** — straight CRUD, no fancy logic.
5. **Models + assets** — model CRUD, multi-asset upload, format badges, 3MF embedded thumbnail extraction, STL viewer on the detail page.
6. **Projects** — CRUD, link filaments, link items (BOM), link models, link printer, status workflow. BOM rollup view per project. Dashboard shopping list aggregating across active projects.
7. **MCP server** — read-only tools first, then the model creation/asset upload tools.
8. **Polish** — dark mode, list filtering, search, pagination where it matters.

Each milestone ends with passing tests, a working UI for what was added, and a `CHANGELOG.md` entry.

## Things to ask before guessing

If something here is ambiguous or contradicts what you find when reading the actual code, ask. Specifically:

- The Spoolman field map keys — worth a check against the live Spoolman API rather than inventing.
- The 3MF thumbnail extraction path — different slicers emit different filenames inside the zip. Check what OrcaSlicer actually does in the user's exports and code defensively with fallbacks.
- New entity types or schema additions ("should printers track filament too?") — these change schema. Ask first.
