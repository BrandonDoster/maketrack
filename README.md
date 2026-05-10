# MakeTrack

Self-hosted 3D printing project tracker with inventory, filament, and pluggable external filament sources (Spoolman first).

Single-user, LAN-only. Ships as a single Docker image on GHCR.

See [`CLAUDE.md`](./CLAUDE.md) for the full project spec, data model, and roadmap.

## Status

Pre-release. M1–M7 complete (skeleton, DB, filaments+sources, inventory+printers, models+assets, projects+BOM, MCP server). M8 polish is the remaining milestone.

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

See `docker-compose.example.yml`. Mount `/data` and `/uploads` as volumes.

## License

AGPL-3.0-or-later. See [`LICENSE`](./LICENSE).
