# Changelog

All notable changes to this project will be documented here. Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Project skeleton: FastAPI app, Pydantic-Settings config, structlog JSON logging, request-id middleware, `/healthz`.
- pyproject + uv lock, ruff config, pytest with httpx async client.
- Multi-stage Dockerfile (uv export -> pip slim image), non-root user, embedded Tailwind compile.
- CI workflow (ruff + pytest) and release workflow (multi-arch GHCR build on `v*.*.*` tags).
