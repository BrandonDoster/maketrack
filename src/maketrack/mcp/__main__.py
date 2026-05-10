"""Run the MCP server over streamable HTTP, bound to localhost only.

Usage:
    uv run python -m maketrack.mcp [--host 127.0.0.1] [--port 8001]

The MCP server has no auth — only bind to addresses you trust. The
default is 127.0.0.1 specifically because CLAUDE.md scopes this to the
same single user that runs the web app.
"""

import argparse

import structlog
import uvicorn

from maketrack.config import get_settings
from maketrack.logging import configure_logging
from maketrack.mcp.server import _http_app
from maketrack.migrations import upgrade_to_head


def main() -> None:
    parser = argparse.ArgumentParser(description="MakeTrack MCP server")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (default: 127.0.0.1, do NOT bind to 0.0.0.0)",
    )
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--no-migrate",
        action="store_true",
        help="skip alembic upgrade head on startup",
    )
    args = parser.parse_args()

    configure_logging(get_settings().log_level)
    log = structlog.get_logger()
    log.info("maketrack.mcp.startup", host=args.host, port=args.port)

    if not args.no_migrate:
        # Same bootstrap the web app does: idempotent on a healthy DB,
        # gets us a usable schema on a fresh /data volume.
        import asyncio

        asyncio.run(upgrade_to_head())
        log.info("maketrack.mcp.migrations_applied")

    uvicorn.run(_http_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
