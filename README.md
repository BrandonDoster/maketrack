# MakeTrack

Self-hosted 3D printing project tracker with inventory, filament, and pluggable external filament sources (Spoolman first).

Single-user, LAN-only. Ships as a single Docker image on GHCR.

See [`CLAUDE.md`](./CLAUDE.md) for the full project spec, data model, and roadmap.

## Status

Pre-release. Milestone 1 (skeleton + healthcheck) is the only thing standing right now.

## Quickstart (dev)

```bash
uv sync --dev
uv run uvicorn maketrack.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
curl http://127.0.0.1:8000/healthz
```

## Quickstart (Docker)

See `docker-compose.example.yml`. Mount `/data` and `/uploads` as volumes.

## License

AGPL-3.0-or-later. See [`LICENSE`](./LICENSE).
