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
- Inventory + printers (M4): straight CRUD, JSON + HTMX UI for both. Inventory has reorder-threshold tracking; the dashboard surfaces a "below reorder" count. Shared `strip_empty_strings` / `format_validation_error` helpers replaced the per-route copies.

### Fixed
- Docker build: `uv export` was emitting both `--hashes` and the project's
  editable line, which pip refuses to mix. Pass `--no-emit-project` and
  install the project separately with `--no-deps`. Also copy `README.md`
  into the final stage (hatchling validates it during the project install).
- Container first-boot 500s: alembic migrations are now applied in the
  FastAPI lifespan via a worker-thread `command.upgrade(...)`, so a fresh
  `/data` volume is bootstrapped automatically. Verified end-to-end: a
  containerized MakeTrack synced 2 spools from a host Spoolman through
  `host.docker.internal`.

### M4 follow-up (UX feedback round)
- Spoolman base-URL placeholder defaults to `http://spoolman:8000` (the
  internal Docker network name), with help text explaining when to use
  `http://host.docker.internal:7912` for an external Spoolman.
- Inventory quantity is now `float`, not `int` — track 1.5m of wire,
  0.25 kg of resin, etc. Schema migration via `batch_alter_table`.
- New `inventory_items` columns: `location` (text), `photo_path` (text).
- Inventory form: `step="0.01"` decimal entry, `onfocus` selects the
  current value so typing replaces it cleanly, `invalid:` Tailwind
  styling highlights bad input in red while typing.
- Inventory items now accept a photo upload (JPEG/PNG/WebP/GIF, 10 MB
  max). New `services/uploads.py` handles streamed save with sha256 +
  size check. Files saved as `inventory/<uuid><ext>` so MIME detection
  works on serve.
- New `/media/{path}` route serves uploaded files with a path-traversal
  guard. Reusable in M5 for model assets.
- Sources UI moved under `/settings/sources`; nav renamed "Sources" →
  "Settings"; new `/settings` overview page.
- Theme system: light / dark / auto (default) via `maketrack_theme`
  cookie. Pre-render JS sets the `dark` class on `<html>` to avoid FOUC.
  All UI templates rethemed with light + dark variants.
- CLAUDE.md: added a "Planned (post-v1)" section sketching schemas for
  printer photo, printer mod list with project link, inventory ↔ printer
  parts tracking with reclaim flow, structured locations, and QR codes
  for items + bins. Removed "Printer mods / maintenance schedules" from
  out-of-scope.

### M5 — models + assets
- Models entity: schemas, service, JSON CRUD (`/api/models`), HTMX UI
  (list grid with thumbnails + format badges, detail page, edit form,
  delete with cascade). Tags stored as JSON-as-text per spec.
- Multi-file asset upload (`POST /api/models/{id}/assets` and the UI
  drop-target on the detail page). Accepts STL, STEP/STP, 3MF, gcode,
  and image types; `asset_type` inferred from file extension. 200 MB
  ceiling per file.
- 3MF embedded thumbnail extraction: on `.3mf` upload, the zip is
  scanned for `Metadata/plate_1.png` / `thumbnail.png` / fallback PNGs
  under `Metadata/`. The thumbnail is saved as a sibling asset
  (`generated=True`); if the model has no `thumbnail_asset_id` set yet,
  it's wired up automatically.
- "Set as thumbnail" UI on any image asset; uploading a fresh image
  also auto-sets it when no thumbnail exists.
- `GET /assets/{id}/download` serves with `Content-Disposition`
  carrying the original filename.
- STL viewer on the model detail page: vendored three.js r170 +
  STLLoader + OrbitControls under `static/vendor/three/`; the importmap
  resolves `three` and `three/addons/` so the unmodified addon files
  load directly. Lazy-loaded via `<script type="module">` only when an
  STL asset is present.
- Tests: 3MF thumbnail extraction (known path, fallback scan, missing
  thumbnail, malformed zip), `asset_type_from_filename`, STL/3MF/image
  upload flows, set-thumbnail validation, Content-Disposition download,
  cascade-delete with thumbnail SET NULL. 89 tests pass total.

### M6 — projects
- Projects entity: schemas, service, JSON CRUD (`/api/projects`), HTMX
  UI (list with status filter chips, detail, edit, delete-cascade).
  Tags stored as JSON-as-text (same pattern as models).
- Status workflow: `planning → printing → done | archived | abandoned`.
  Status quick-action bar on the detail page; transitioning to `done`
  auto-stamps `completed_at`, transitioning back clears it.
- Project ↔ model links (`project_models`): qty_to_print + per-link
  status + notes. Idempotent re-link upserts on the composite PK so
  the UI's "add model" form is safe to repeat.
- Project ↔ filament links (`project_filaments`): est/actual weight,
  role (`extruder_0`, `supports`, etc.). Hydrated read endpoints expose
  filament name/color/source so the UI doesn't N+1.
- Project ↔ inventory links (`project_items`): qty_required +
  qty_consumed. Migration 0003 promotes both columns to `REAL` so
  fractional quantities match the M4-followup inventory schema.
- BOM rollup (`GET /api/projects/{id}/bom`) per CLAUDE.md formula:
  `still_needed = qty_required - qty_consumed`,
  `still_to_buy = max(0, still_needed - on_hand)`. Detail page table
  highlights "still to buy > 0" rows in amber.
- Cross-project shopping list (`GET /api/shopping-list`): aggregates
  demand across `status in (planning, printing)` projects, subtracts
  on-hand once per item, lists the project IDs needing it. Surfaced as
  a section on the dashboard.
- Dashboard "Projects coming in M6" placeholder replaced by an active
  project tile + the live shopping list.
- Tests: project CRUD + status auto-stamp/clear, idempotent model
  linking, decimal qty_required, BOM rollup (covered / short /
  consumed), shopping list aggregation (sums demand, excludes inactive,
  omits covered items), UI smoke. 108 tests pass total.

### M6 follow-up (UX feedback round)
- Project-side file upload: drop STL/STEP/3MF/gcode files on a project
  and each becomes a new Model named after the filename, auto-linked
  with qty_to_print=1. 3MF embedded thumbnails still extract. Image
  files on this endpoint are skipped (they belong to the photo flow).
- Custom (unlinked) BOM items: migration 0004 makes
  `project_items.inventory_item_id` nullable and adds `name` + `unit`.
  The detail page has two "Add" forms — pick from inventory or type a
  free-text item with qty + unit. Per-row "link to…" dropdown on
  unlinked rows attaches a real inventory item later, preserving the
  typed name. BOM rollup + shopping list both handle unlinked rows
  (`on_hand=null`, `still_to_buy=still_needed`).
- Project photos: two slots (cover + completed) on `projects` via
  migration 0004. Upload / replace / remove from the detail page; old
  files are unlinked from disk when replaced or removed.
- CLAUDE.md "Planned" updated with the slicer-aware filament estimator
  (presets + 3MF metadata + per-link override) and the standard
  hardware autocomplete via curated `<datalist>` JSON.
- Verified end-to-end through Docker: project upload turned two STLs
  into linked Models; a custom "M3x12 SHCS" BOM row reported
  `on_hand=null still_to_buy=50`, late-linking to a 20-on-hand
  inventory item flipped the same row to `on_hand=20 still_to_buy=30`;
  cover photo round-tripped via `/media/projects/<uuid>.png`; shopping
  list rendered linked + unlinked rows together. 119 tests pass.

### M6 polish (second feedback round)
- Project list cards show the cover photo (or completed photo if no
  cover) so a grid of in-flight projects is scannable visually.
- BOM rows have inline number inputs for qty_required and qty_consumed
  that auto-submit on change (`onchange="this.form.submit()"`). Bad
  input is silently ignored — the input snaps back to the saved value
  on the next render.
- Project notes are now an inline textarea + Save form on the detail
  page so progress journaling doesn't require navigating to /edit.
  Empty/whitespace-only saves clear the column to NULL.
- Verified end-to-end: cover image rendered on `/projects` cards;
  inline qty edit `required=80, consumed=15` → BOM `still_needed=65,
  still_to_buy=55`; inline notes saved and round-tripped through the
  detail page. 126 tests pass.

### Fixed — clearing nullable text fields via edit forms
- Bug: clearing description / notes (or any nullable text field) in any
  edit form silently kept the old value. The shared
  `strip_empty_strings` helper dropped empty-string keys from the
  payload, and Pydantic's `exclude_unset=True` then read that as "no
  change" rather than "set to NULL."
- Fix: added `null_empty_strings` (sibling helper) that keeps every key
  but turns empty/whitespace-only strings into `None`, so the PATCH
  payload says "clear this field." Applied to every UI update route —
  projects, filaments, inventory, printers, models, sources. Create
  routes still use `strip_empty_strings` so schema defaults apply.
- Also stripped the `notes` textarea from the project edit form; that
  field lives inline on the detail page now and was duplicated with
  conflicting save semantics.
- Verified end-to-end through Docker: editing a project with a cleared
  description via the form persisted `description=null`; the edit form
  contains zero instances of `name="notes"`. 129 tests pass.

### M6 polish round 2 (third feedback round)
- BOM edits no longer full-page-refresh. Extracted `_bom_section.html`
  partial; qty/add/link/delete UI routes detect `HX-Request` and return
  the partial for HTMX swaps. The user's scroll position survives.
- New BOM rows are entered inline at the bottom of the table — type
  name, tab to required, tab to consumed, tab to the link select,
  blur-out commits via HTMX. The empty entry row reappears at the
  bottom and auto-focuses for the next entry. Replaces the two
  separate "Add from inventory" / "Add custom item" forms below the
  table.
- `qty_to_print` on project_models is now an inline number input,
  HTMX-swap into `_models_section.html`. New `POST
  /projects/{id}/models/{model_id}/qty` route updates it.
- Hidden the browser spin buttons on `<input type="number">` via
  global CSS — typing is faster than clicking the carets and they ate
  space in tight cells.
- Photos restructured: detail page header now shows a small Alpine
  tabbed thumbnail (Cover | After) next to the project name; clicking
  the photo opens a lightbox overlay. Upload / replace / remove forms
  moved to the project edit page (the detail page just consumes the
  photos visually).
- Verified end-to-end through Docker: HTMX qty edit returned the
  `#bom-section` partial; new custom BOM row entry persisted
  ("Heatset M3", req 12); model qty_to_print updated to 7; detail
  page has the tabbed-thumbnail + lightbox markup and zero upload
  forms; edit page has both photo upload forms and zero notes
  textarea. 137 tests pass.

### M6 polish round 3 (fourth feedback round)
- Description moved out of its own card and into the project detail
  header — sits between the title row and the status row, the way you'd
  read it on a card. The standalone "Description" section is gone.
- Printer info moved out of the title block and into the right side of
  the status quick-action row, so the title is just title + status chip
  + description.
- Notes is now a single full-width section (no more side-by-side with
  description) and the textarea auto-grows as the user types via Alpine
  `@input` resizing.
- Inline status select on each project_model row (pending / printed /
  failed). New `POST /projects/{id}/models/{model_id}/status` endpoint
  validates the value, rejects anything outside the allowed set, and
  returns the models-section HTMX partial. The link's status belongs to
  the project link — the same model can be 'pending' on one project and
  'printed' on another.
- Verified end-to-end through Docker: detail page rendered the
  description inline, the printer in the status row, and the model
  status select; flipping status via HTMX persisted to `printed`;
  invalid `shipped` value silently ignored. 143 tests pass.

### Models list — multiple views + project-scope filter
- Each model card / row now carries an "in N project(s)" chip when
  it's linked to one or more projects. Derived from `project_models`
  at query time (no denormalization). Hover-title lists the project
  names.
- Three view modes for the models list, switchable via toolbar
  buttons: **Cards** (current grid), **Details** (table with
  thumbnail / name / source / formats / asset count / projects /
  tags / updated_at — Windows Explorer-style), **List** (compact
  one-line rows). Choice is URL-driven (`?view=details`) so views are
  bookmarkable.
- New filter: "hide project-scoped models" toggle. When on, models
  attached to any project are excluded from the list — keeps the
  global library a curated set of standalone designs (Printables /
  Thingiverse / your own creations) without the noise of 30 small
  parts that belong to a printer build. URL param
  `?hide_project_models=true`; toolbar preserves view + filter across
  toggles.
- New service helper `list_models_with_context()` hydrates
  thumbnail/formats/asset count/project names in three flat queries
  instead of N+1.
- Empty-state copy tells the user *why* the list is empty (e.g.
  "All your models are scoped to projects. Toggle the filter off to
  see them.") so the filter doesn't look like a bug.
- Verified end-to-end through Docker: cards / details / list each
  render their distinctive markup; "in 1 project" chip appears on
  project-linked models; `hide_project_models=true` collapses the
  list to just the standalone library model. 152 tests pass.

### Models list — tags visible in details + saveable defaults
- Bumped the tag/format chip font from `text-[10px]` (an arbitrary
  Tailwind value at risk of being culled by the CLI build) to the
  standard `text-xs` so chips render reliably in the static build.
- Added the "in N project(s)" chip to the Name column in details view
  so each row shows project membership at a glance regardless of
  user-added tags. Empty Tags cell now renders an em-dash placeholder.
- New "Save as default" button on the toolbar — persists the current
  view + filter as cookies (`maketrack_models_view`,
  `maketrack_models_hide_project_models`) so subsequent visits to
  `/models` with no query params open with those settings. Explicit
  `?view=` query params still win, so the user can poke other views
  without losing their saved default. New `POST /models/preferences`
  validates the value, falls back to `cards` for unknown views.
- Verified end-to-end: details view rendered `voron` + `filter` chips,
  Tags column header, and the "in 1 project" chip; saving prefs set
  both cookies; follow-up unparam'd GET landed on details view with
  the filter active and the project-scoped row hidden. 157 tests pass.

### M7 — MCP server
- New `mcp` Python dep; package skeleton at `src/maketrack/mcp/`.
- `FastMCP` server exposes 11 tools — 8 read + 3 write — backed by the
  existing async services so the LLM client and the web UI see the
  same data:
  - **read**: `list_projects`, `get_project` (with linked
    models/filaments/items/printer), `list_models`, `get_model`
    (with assets), `list_filaments`, `find_filament_for_project`
    (returns `coverage` of `'covered' | 'short' | 'unknown'` per
    project_filament), `project_shopping_list` (per project or
    aggregated across active projects), `list_printers`,
    `list_inventory`.
  - **write** (scoped per CLAUDE.md): `create_model`,
    `upload_model_asset` (base64 content, asset_type inferred from
    filename, 3MF embedded thumbnails extracted automatically),
    `set_model_thumbnail`.
- `serializers.py` keeps the ORM↔dict conversion in one place so each
  tool's payload shape is consistent.
- `python -m maketrack.mcp` runs the streamable-http transport,
  defaults to `--host 127.0.0.1 --port 8001`. No auth — same single
  user assumption as the web app, scoped to localhost.
- Migrations bootstrap on startup the same way the web app does.
- Tests call the tool functions directly (FastMCP's `@tool()`
  decorator returns the function unchanged) — covers happy path +
  error cases for all 11 tools.
- README updated with the run command + tool table. 171 tests pass.

### M8 — search + filter polish
- Each of the five list pages (filaments, inventory, models, projects,
  printers) now has a `?q=...` search box wired to a server-side
  `name ILIKE %q%` (case-insensitive on ASCII via SQLite default
  collation). Empty-state copy is context-aware: "No matches for X" with
  a Clear-filters link, vs. the standard "no rows yet" hint when the
  list is genuinely empty.
- Filter UIs were missing for the API filters that already existed —
  exposed them now: filaments get material (populated from a distinct
  query of what's actually in the table) + source dropdowns, inventory
  gets a category dropdown plus a "below reorder" toggle that shows
  only items at or under their reorder threshold.
- Models toolbar gains a search input alongside the existing view
  switcher, hide-project filter, and save-as-default button. Search is
  preserved across view changes via URL param.
- Projects status chips preserve the active search; the search form
  preserves the active status as a hidden input. Round-trips cleanly.
- Pagination deferred. At realistic homelab scales (<200 rows per
  list) it's noise — added a "Planned (post-v1)" note in CLAUDE.md
  with the shape we'd want when it matters.
- Verified end-to-end through Docker: all five lists filtered
  correctly, empty states rendered the search query, "below reorder"
  collapsed to just the under-threshold item. 185 tests pass.

### M9 — pagination
- Pagination on the three lists that can grow without bound: filaments,
  inventory, models. Default page size 50, override via `?page=N`.
  Skip on projects + printers (low cardinality, per spec).
- New `services/_pagination.py` with a `Page[T]` dataclass that owns
  the math (`has_prev`, `has_next`, `total_pages`, `first_index`,
  `last_index`) plus `normalize_page()` that clamps out-of-range page
  numbers to the last valid page so a stale bookmark never 404s.
- `count_filaments()` / `count_items()` siblings share their filter
  builder with the list functions so total counts always reflect the
  same WHERE clauses as the rendered slice. `list_models_with_context`
  now returns a `Page[ModelListEntry]` directly — the in-Python filter
  pass (tag, hide-project) produces both the slice and the count.
- `_pagination.html` partial: prev/next chips with a disabled state at
  edges, "first–last of total · page X of Y" copy. Renders nothing
  when total fits on one page so small lists stay clean.
- Query-string preservation: each route builds a `query_base` with all
  current filters via a new `query_string()` helper in `_forms.py`
  that drops empty/None/False values; the partial concatenates
  `?{query_base}&page=N`. Search, view, hide-project, category,
  below-reorder, etc. all carry across page navigation.
- Existing service signatures stay backward-compatible — `page` /
  `page_size` are optional keyword-only args that default to None,
  meaning "no pagination, return everything." MCP tools and JSON
  routes continue to return all rows.
- Tests cover the Page math at edges, page=1 / page=2 / page=99
  clamping, no-footer-on-small-lists, and query-string preservation
  across search + view + filter combinations.
- Verified end-to-end through Docker with 75 seeded inventory rows:
  page 1 shows "page 1 of 2", page 2 shows "page 2 of 2", page=99
  clamps to page 2, category filter survives prev-page navigation.
  195 tests pass.

### M10 — hardware-preset autocomplete
- Static `static/hardware-presets.json` with 103 starter entries
  covering common 3D-printing parts: M2/M2.5/M3/M5 SHCS+BHCS+FHCS in
  the lengths people actually buy, heatset inserts, nuts/washers,
  T-nuts, bearings (F62x, MR105), GT2 belts/pulleys, MGN9/MGN12
  rails, T8 leadscrews, PTFE tubing, hotends, nozzles, BMG gears,
  NEMA17 steppers, thermistors, fans, XT60/XT30, silicone wire.
  Easy to extend by editing the JSON.
- `static/hardware-presets.js` self-wires every
  `<input data-hardware-preset="<unit-field-name>">` on the page to a
  shared generated `<datalist>` and prefills the linked unit field
  when a recognized preset is picked — but never overwrites a unit
  the user already typed manually. Self-skipping: if no inputs match,
  the JSON fetch never fires.
- Wired on the inventory create/edit form's `name` input (fills the
  visible `unit` input) and the BOM custom-item entry row on the
  project detail page (fills a hidden `unit` input that's part of the
  same form, so the JS-set value survives form submission).
- Loaded globally via base.html so any future input that opts in via
  the data attribute gets the behavior automatically.
- Verified end-to-end through Docker: 103 presets served from JSON,
  inventory form + BOM entry row both carry the wiring attribute,
  BOM row has the hidden unit input. Removed the autocomplete entry
  from the CLAUDE.md "Planned" section. 202 tests pass.

### M11 — locations
- New `locations` table (`id, name UNIQUE, kind, parent_id, qr_code,
  created_at, updated_at`). Kind enum stays storage-scale —
  `bin | shelf | drawer | other` — no rooms or buildings. `parent_id`
  and `qr_code` ship in the schema for future nesting and the planned
  QR-scan flow but aren't exposed in the UI yet.
- Migration 0005 promotes the old `inventory_items.location` text
  field: creates the table, adds an `inventory_items.location_id` FK
  with `ON DELETE SET NULL`, backfills one row per distinct existing
  string (kind defaulted to `other` so backfilled values are visible
  but distinguishable from intentional bin/shelf assignments), repoints
  the items, then drops the old column. Round-trip downgrade restores
  the text values.
- `Location` ORM model + `InventoryItem.location` relationship
  (`lazy="joined"` so list views and serializers don't need to
  remember to eager-load).
- API at `/api/locations` (CRUD with 409 on duplicate name) and a
  Settings sub-page at `/settings/locations` for the UI: inline create
  form, table with item-count column, edit page, delete with confirm.
- Inventory form swaps the free-text location input for a select of
  existing locations plus a "Manage locations →" link. Inventory list
  renders `it.location.name`. MCP `inventory_item` serializer follows
  suit, returning the location name as a string.
- Settings index gets a Locations card alongside External sources and
  Appearance; the "future milestones" placeholder shrinks to just QR
  codes and printer mods.
- Tests: locations CRUD, duplicate-name 409, invalid-kind 422, FK
  set-null on delete, settings UI flow (create/edit/delete redirects),
  inventory form renders the select and posts location_id, inventory
  list renders the name, settings page links to /settings/locations.
  Migration test seeds rows at revision 0004 with the old text field
  and asserts both that distinct strings collapse into the right
  number of locations rows and that NULLs stay NULL after the upgrade.
  216 tests pass.
