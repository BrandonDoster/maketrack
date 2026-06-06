<p align="left">
  <img src="src/maketrack/static/brand/maketrack-wordmark.svg#gh-light-mode-only" alt="maketrack" height="56">
  <img src="src/maketrack/static/brand/maketrack-wordmark-dark.svg#gh-dark-mode-only" alt="maketrack" height="56">
</p>

Self-hosted 3D printing project tracker with inventory, filament, and pluggable external filament sources (Spoolman first).

Single-user, LAN-only. Ships as a single Docker image on GHCR.

See [`CLAUDE.md`](./CLAUDE.md) for the full project spec, data model, and roadmap.

## Status

v0.1.0 cut, plus active work on `dev`. All entities (projects, models, printers, filaments, inventory, locations) are reachable through the UI and a read-only MCP server. Detail pages share a read/edit toggle; most use a draft-stub create flow, while **models** are filesystem-backed (one folder per model under `/maketrack-models`, with a `README.md` + `photos/` + `models/`) and use a deferred create form that commits nothing until you hit Save. The library can be edited directly on disk over a share and reconciled with a "Sync from disk" scan.

## Quickstart (dev)

```bash
uv sync --dev
uv run uvicorn maketrack.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
curl http://127.0.0.1:8000/healthz
```

## MCP server

A read-only-by-default MCP server lives in `src/maketrack/mcp/`. It speaks
the [Model Context Protocol](https://modelcontextprotocol.io/) over
streamable HTTP and shares the SQLite database with the web app, so tools
like `list_projects`, `find_filament_for_project`, and
`project_shopping_list` see the same data the UI does.

```bash
# Bind to localhost only — there's no auth, you don't want this exposed.
uv run python -m maketrack.mcp --host 127.0.0.1 --port 8001
```

Tools available:

| read                         | write (scoped to model creation) |
|------------------------------|----------------------------------|
| `list_projects`              | `create_model`                   |
| `get_project`                | `upload_model_asset`             |
| `list_models`                | `set_model_thumbnail`            |
| `get_model`                  |                                  |
| `list_filaments`             |                                  |
| `find_filament_for_project`  |                                  |
| `project_shopping_list`      |                                  |
| `list_printers`              |                                  |
| `list_inventory`             |                                  |

## Quickstart (Docker)

See `docker-compose.example.yml`. Mount `/data`, `/uploads`, and
`/maketrack-models` as volumes (DB, photos, and the model library
respectively).

The container runs as **UID/GID `1000:1000`** (matches the default first-user
UID on most desktop Linux distros). When you bind-mount host directories for
those paths, they need to be writable by that UID:

```bash
mkdir -p maketrack-data maketrack-uploads maketrack-models
sudo chown -R 1000:1000 maketrack-data maketrack-uploads maketrack-models
```

If your host user is already UID 1000, the chown is a no-op. If not, either
run the chown above or override the container user in compose to match your
host UID:

```yaml
services:
  maketrack:
    user: "${UID}:${GID}"
```

Symptom if you skip this: startup fails with
`sqlite3.OperationalError: unable to open database file`.

### Editing the model library directly

`./maketrack-models` is a plain folder (one subfolder per model, each with a
`README.md` + `photos/` + `models/`). You can add, edit, or delete model files
directly however you like — a local file manager, rsync, Syncthing, an NFS
export, etc. maketrack reconciles on-disk changes via its daily scan, the
**Sync from disk** button on the Models page, and a scoped rescan whenever you
open a model.

To mount it as a network drive from Mac, Windows, and Linux, uncomment the
optional [`dockurr/samba`](https://github.com/dockur/samba) sidecar in
`docker-compose.example.yml`. It serves the same `./maketrack-models` directory
over SMB in its own container (the app container stays non-root). Default login
is `samba` / `secret` — change it. Windows refuses anonymous SMB, so it always
needs that login; Mac and Linux can use it too or mount as guest.

## License

AGPL-3.0-or-later. See [`LICENSE`](./LICENSE).
